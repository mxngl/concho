from __future__ import annotations

from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUTS_DIR = BASE_DIR / "inputs"
OUTPUTS_DIR = BASE_DIR / "outputs"
PLANNING_ENGINE_DIR = BASE_DIR.parent

WORKBOOK_PATH = INPUTS_DIR / "ALICE_macro.xlsx"
MICRO_SCHEDULE_PATH = PLANNING_ENGINE_DIR / "Micro_Schedule_Generator" / "outputs" / "Micro_Schedule.csv"
OUTPUT_XML_PATH = OUTPUTS_DIR / "ALICE_Task_Schedule.xml"
OUTPUT_MACRO_VIEW_PATH = OUTPUTS_DIR / "ALICE_Task_Schedule_Macro_View.csv"

NS = "http://xmlns.oracle.com/Primavera/P6/V25.12/API/BusinessObjects"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("", NS)
ET.register_namespace("xsi", XSI)


def qname(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def add_text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    element = ET.SubElement(parent, qname(tag))
    element.text = "" if value is None else str(value)
    return element


def p6_guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def format_dt(value: object) -> str:
    return pd.to_datetime(value).isoformat(timespec="seconds")


def normalize_level(value: object) -> str:
    text = clean_text(value)
    return text if text else "Unassigned"


def safe_token(value: object) -> str:
    text = clean_text(value).replace("-", "M")
    token = "".join(ch if ch.isalnum() else "_" for ch in text)
    return "_".join(part for part in token.split("_") if part)


def level_sort_key(level: object) -> tuple[float, str]:
    text = normalize_level(level)
    if text.casefold() == "basement / site":
        return (-100.0, text)
    if text.casefold() == "unassigned":
        return (9998.0, text)
    if text.casefold() == "roof":
        return (9000.0, text)
    match = "".join(ch if ch.isdigit() or ch == "-" else " " for ch in text).split()
    if match:
        return (float(match[0]), text)
    return (9500.0, text)


def elapsed_hours_between(start: pd.Timestamp, finish: pd.Timestamp) -> float:
    if finish <= start:
        return 0.0

    return (finish - start).total_seconds() / 3600.0


def load_wbs_lookup() -> pd.DataFrame:
    if not WORKBOOK_PATH.exists():
        return pd.DataFrame(columns=["task_id", "wbs_name", "wbs_code"])

    workbook = pd.ExcelFile(WORKBOOK_PATH)
    tasks = workbook.parse("Tasks", dtype=str).fillna("")
    wbs = workbook.parse("WBS", dtype=str).fillna("")

    wbs_lookup = wbs[["Alice WBS Id*", "Name*", "Code -  read only"]].rename(
        columns={
            "Name*": "wbs_name",
            "Code -  read only": "wbs_code",
        }
    )
    merged = tasks.merge(
        wbs_lookup,
        on="Alice WBS Id*",
        how="left",
    )
    return pd.DataFrame(
        {
            "task_id": merged["Id*"].apply(clean_text),
            "wbs_name": merged["wbs_name"].apply(clean_text),
            "wbs_code": merged["wbs_code"].apply(clean_text),
        }
    )


def activity_id(task_id: str, level: str) -> str:
    level_token = safe_token(level)
    return f"{safe_token(task_id)}_{level_token}"[:40]


def build_activity_table() -> pd.DataFrame:
    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    required_columns = {"task_id", "task_name", "level", "element_id", "element_start", "element_end"}
    missing_columns = required_columns.difference(micro.columns)
    if missing_columns:
        raise ValueError(
            f"{MICRO_SCHEDULE_PATH.name} is missing required columns: {sorted(missing_columns)}"
        )

    micro["element_start_ts"] = pd.to_datetime(micro["element_start"], format="mixed")
    micro["element_end_ts"] = pd.to_datetime(micro["element_end"], format="mixed")
    micro["level"] = micro["level"].apply(normalize_level)

    grouped = (
        micro.groupby(["task_id", "task_name", "level"], dropna=False)
        .agg(
            start=("element_start_ts", "min"),
            finish=("element_end_ts", "max"),
            element_count=("element_id", "nunique"),
        )
        .reset_index()
        .sort_values(["start", "task_id", "task_name", "level"])
        .reset_index(drop=True)
    )
    grouped["level_sort"] = grouped["level"].apply(level_sort_key)

    grouped["duration_hours"] = grouped.apply(
        lambda row: max(
            elapsed_hours_between(row["start"], row["finish"]),
            1 / 60,
        ),
        axis=1,
    )
    grouped["activity_id"] = grouped.apply(lambda row: activity_id(row["task_id"], row["level"]), axis=1)
    grouped["activity_name"] = grouped["task_id"] + " " + grouped["task_name"] + " | " + grouped["level"]

    wbs_lookup = load_wbs_lookup()
    grouped = grouped.merge(wbs_lookup, on="task_id", how="left")
    grouped["wbs_name"] = grouped["wbs_name"].replace("", pd.NA).fillna("ALICE Tasks")
    grouped["wbs_code"] = grouped["wbs_code"].replace("", pd.NA).fillna("alice_tasks")
    return grouped


def write_macro_view(activities: pd.DataFrame) -> None:
    macro_view = activities.loc[
        :,
        [
            "activity_id",
            "activity_name",
            "task_id",
            "task_name",
            "level",
            "start",
            "finish",
            "duration_hours",
            "element_count",
            "wbs_name",
            "wbs_code",
        ],
    ].copy()
    macro_view.to_csv(OUTPUT_MACRO_VIEW_PATH, index=False)


def build_finish_to_start_relationships(activities: pd.DataFrame) -> list[tuple[str, str]]:
    ordered = activities.sort_values(["start", "finish", "task_id", "level"]).reset_index(drop=True)
    relationships: list[tuple[str, str]] = []

    for _, successor in ordered.iterrows():
        candidates = ordered[ordered["finish"] <= successor["start"]].copy()
        candidates = candidates[candidates["activity_id"] != successor["activity_id"]]
        if candidates.empty:
            continue

        latest_finish = candidates["finish"].max()
        immediate_predecessors = candidates[candidates["finish"] == latest_finish]
        for _, predecessor in immediate_predecessors.iterrows():
            relationships.append((clean_text(predecessor["activity_id"]), clean_text(successor["activity_id"])))

    return list(dict.fromkeys(relationships))


def add_default_currency(root: ET.Element) -> None:
    currency = ET.SubElement(root, qname("Currency"))
    add_text(currency, "DecimalPlaces", 2)
    add_text(currency, "DecimalSymbol", "Period")
    add_text(currency, "DigitGroupingSymbol", "Comma")
    add_text(currency, "ExchangeRate", 1)
    add_text(currency, "Id", "CUR")
    add_text(currency, "Name", "Default Currency")
    add_text(currency, "NegativeSymbol", "(#1.1)")
    add_text(currency, "ObjectId", 1)
    add_text(currency, "PositiveSymbol", "#1.1")
    add_text(currency, "Symbol", "$")


def add_default_calendar(root: ET.Element) -> None:
    calendar = ET.SubElement(root, qname("Calendar"))
    add_text(calendar, "HoursPerDay", 8)
    add_text(calendar, "HoursPerMonth", 160)
    add_text(calendar, "HoursPerWeek", 40)
    add_text(calendar, "HoursPerYear", 1920)
    add_text(calendar, "IsDefault", 1)
    add_text(calendar, "IsPersonal", 0)
    add_text(calendar, "Name", "Default calendar")
    add_text(calendar, "ObjectId", 4)
    add_text(calendar, "Type", "Global")

    standard_work_week = ET.SubElement(calendar, qname("StandardWorkWeek"))
    for day in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
        day_hours = ET.SubElement(standard_work_week, qname("StandardWorkHours"))
        add_text(day_hours, "DayOfWeek", day)
        if day not in {"Sunday", "Saturday"}:
            work_time = ET.SubElement(day_hours, qname("WorkTime"))
            add_text(work_time, "Start", "09:00:00")
            add_text(work_time, "Finish", "16:59:00")
    ET.SubElement(calendar, qname("HolidayOrExceptions"))


def add_project_defaults(project: ET.Element, project_start: str, project_finish: str) -> None:
    add_text(project, "ActivityDefaultActivityType", "Task Dependent")
    add_text(project, "ActivityDefaultCalendarObjectId", 4)
    add_text(project, "ActivityDefaultDurationType", "Fixed Duration and Units")
    add_text(project, "ActivityDefaultPercentCompleteType", "Duration")
    add_text(project, "ActivityDefaultPricePerUnit", 0)
    add_text(project, "ActivityIdBasedOnSelectedActivity", 1)
    add_text(project, "ActivityIdIncrement", 10)
    add_text(project, "ActivityIdPrefix", "A")
    add_text(project, "ActivityIdSuffix", "1000")
    add_text(project, "ActivityPercentCompleteBasedOnActivitySteps", 0)
    add_text(project, "AddActualToRemaining", 0)
    add_text(project, "AllowNegativeActualUnitsFlag", 0)
    add_text(project, "AssignmentDefaultDrivingFlag", 1)
    add_text(project, "AssignmentDefaultRateType", "Price / Unit")
    add_text(project, "CheckOutStatus", 0)
    add_text(project, "CostQuantityRecalculateFlag", 0)
    add_text(project, "CriticalActivityFloatLimit", 0)
    add_text(project, "CriticalActivityPathType", "Critical Float")
    add_text(project, "DataDate", project_start)
    add_text(project, "DefaultPriceTimeUnits", "Hour")
    add_text(project, "FinishDate", project_finish)
    add_text(project, "FiscalYearStartMonth", 1)
    add_text(project, "GUID", p6_guid())
    add_text(project, "Id", "ALICE Task Schedule")
    add_text(project, "LevelingPriority", 10)
    add_text(project, "LinkActualToActualThisPeriod", 1)
    add_text(project, "LinkPercentCompleteWithActual", 1)
    add_text(project, "LinkPlannedAndAtCompletionFlag", 1)
    add_text(project, "Name", "ALICE Task Schedule")
    add_text(project, "ObjectId", 1)
    add_text(project, "PlannedStartDate", project_start)
    add_text(project, "ProjectFlag", 1)
    add_text(project, "StartDate", project_start)
    add_text(project, "Status", "Active")

    project_calendar = ET.SubElement(project, qname("Calendar"))
    add_text(project_calendar, "ObjectId", 4)


def build_xml() -> ET.ElementTree:
    activities = build_activity_table()
    if activities.empty:
        raise ValueError(f"No activities found in {MICRO_SCHEDULE_PATH}")
    write_macro_view(activities)

    project_start = format_dt(activities["start"].min())
    project_finish = format_dt(activities["finish"].max())

    root = ET.Element(qname("APIBusinessObjects"), {f"{{{XSI}}}schemaLocation": ""})
    add_default_currency(root)
    add_default_calendar(root)

    project = ET.SubElement(root, qname("Project"))
    add_project_defaults(project, project_start, project_finish)

    root_wbs_object_id = 100
    root_wbs = ET.SubElement(project, qname("WBS"))
    add_text(root_wbs, "Code", "1")
    add_text(root_wbs, "GUID", p6_guid())
    add_text(root_wbs, "Name", "ALICE TASK SCHEDULE")
    add_text(root_wbs, "ObjectId", root_wbs_object_id)
    add_text(root_wbs, "ParentObjectId", "")
    add_text(root_wbs, "ProjectObjectId", 1)
    add_text(root_wbs, "SequenceNumber", 1)
    add_text(root_wbs, "Status", "Active")

    task_wbs_object_ids: dict[str, int] = {}
    level_wbs_object_ids: dict[tuple[str, str], int] = {}
    next_wbs_object_id = 110
    ordered_tasks = (
        activities.loc[:, ["task_id", "task_name", "start"]]
        .drop_duplicates(subset=["task_id", "task_name"])
        .sort_values(["start", "task_id", "task_name"])
        .reset_index(drop=True)
    )

    for task_sequence, (_, task_row) in enumerate(
        ordered_tasks.iterrows(),
        start=1,
    ):
        task_id = clean_text(task_row["task_id"])
        task_name = clean_text(task_row["task_name"])
        task_wbs_object_ids[task_id] = next_wbs_object_id
        wbs = ET.SubElement(project, qname("WBS"))
        add_text(wbs, "Code", f"1.{task_sequence}")
        add_text(wbs, "GUID", p6_guid())
        add_text(wbs, "Name", f"{task_id} {task_name}")
        add_text(wbs, "ObjectId", next_wbs_object_id)
        add_text(wbs, "ParentObjectId", root_wbs_object_id)
        add_text(wbs, "ProjectObjectId", 1)
        add_text(wbs, "SequenceNumber", task_sequence)
        add_text(wbs, "Status", "Active")

        task_parent_object_id = next_wbs_object_id
        next_wbs_object_id += 10

        task_levels = (
            activities[activities["task_id"] == task_id]
            .loc[:, ["level", "level_sort", "start"]]
            .drop_duplicates(subset=["level"])
            .sort_values(["level_sort", "start", "level"])
            .reset_index(drop=True)
        )
        for level_sequence, (_, level_row) in enumerate(task_levels.iterrows(), start=1):
            level = normalize_level(level_row["level"])
            level_wbs_object_ids[(task_id, level)] = next_wbs_object_id
            level_wbs = ET.SubElement(project, qname("WBS"))
            add_text(level_wbs, "Code", f"1.{task_sequence}.{level_sequence}")
            add_text(level_wbs, "GUID", p6_guid())
            add_text(level_wbs, "Name", level)
            add_text(level_wbs, "ObjectId", next_wbs_object_id)
            add_text(level_wbs, "ParentObjectId", task_parent_object_id)
            add_text(level_wbs, "ProjectObjectId", 1)
            add_text(level_wbs, "SequenceNumber", level_sequence)
            add_text(level_wbs, "Status", "Active")
            next_wbs_object_id += 10

    activity_object_id_map: dict[str, int] = {}
    next_activity_object_id = 1000
    for _, row in activities.iterrows():
        task_activity_id = clean_text(row["activity_id"])
        activity_object_id_map[task_activity_id] = next_activity_object_id
        start_dt = format_dt(row["start"])
        finish_dt = format_dt(row["finish"])
        duration_hours = round(float(row["duration_hours"]), 4)

        activity = ET.SubElement(project, qname("Activity"))
        add_text(activity, "ActualLaborUnits", 0)
        add_text(activity, "ActualNonLaborUnits", 0)
        add_text(activity, "AtCompletionDuration", duration_hours)
        add_text(activity, "AutoComputeActuals", 1)
        add_text(activity, "CalendarObjectId", 4)
        add_text(activity, "DurationType", "Fixed Units/Time")
        add_text(activity, "FinishDate", finish_dt)
        add_text(activity, "GUID", p6_guid())
        add_text(activity, "Id", task_activity_id)
        add_text(activity, "LevelingPriority", "Normal")
        add_text(activity, "Name", clean_text(row["activity_name"]))
        add_text(activity, "ObjectId", next_activity_object_id)
        add_text(activity, "PercentCompleteType", "Duration")
        add_text(activity, "PlannedDuration", duration_hours)
        add_text(activity, "PlannedFinishDate", finish_dt)
        add_text(activity, "PlannedLaborUnits", duration_hours)
        add_text(activity, "PlannedNonLaborUnits", 0)
        add_text(activity, "PlannedStartDate", start_dt)
        add_text(activity, "PrimaryResourceObjectId", "")
        add_text(activity, "ProjectObjectId", 1)
        add_text(activity, "RemainingDuration", duration_hours)
        add_text(activity, "RemainingEarlyFinishDate", finish_dt)
        add_text(activity, "RemainingEarlyStartDate", start_dt)
        add_text(activity, "RemainingLaborCost", 0)
        add_text(activity, "RemainingLaborUnits", duration_hours)
        add_text(activity, "RemainingLateFinishDate", finish_dt)
        add_text(activity, "RemainingLateStartDate", start_dt)
        add_text(activity, "RemainingNonLaborCost", 0)
        add_text(activity, "RemainingNonLaborUnits", 0)
        add_text(activity, "StartDate", start_dt)
        add_text(activity, "Status", "Not Started")
        add_text(activity, "Type", "Task Dependent")
        add_text(
            activity,
            "WBSObjectId",
            level_wbs_object_ids[(clean_text(row["task_id"]), normalize_level(row["level"]))],
        )

        note = ET.SubElement(project, qname("ActivityNote"))
        add_text(note, "ActivityObjectId", next_activity_object_id)
        add_text(
            note,
            "Note",
            (
                f"&lt;b&gt;Task ID:&lt;/b&gt; {row['task_id']}"
                f" &lt;br/&gt;&lt;b&gt;Level:&lt;/b&gt; {row['level']}"
                f" &lt;br/&gt;&lt;b&gt;Micro Elements Aggregated:&lt;/b&gt; {row['element_count']}"
            ),
        )
        add_text(note, "NotebookTopicObjectId", 2)
        add_text(note, "ObjectId", next_activity_object_id + 1)
        add_text(note, "ProjectObjectId", 1)

        next_activity_object_id += 10

    relationship_object_id = 5000
    for predecessor_activity_id, successor_activity_id in build_finish_to_start_relationships(activities):
        relationship = ET.SubElement(project, qname("Relationship"))
        add_text(relationship, "Lag", 0)
        add_text(relationship, "ObjectId", relationship_object_id)
        add_text(relationship, "PredecessorActivityObjectId", activity_object_id_map[predecessor_activity_id])
        add_text(relationship, "PredecessorProjectObjectId", 1)
        add_text(relationship, "SuccessorActivityObjectId", activity_object_id_map[successor_activity_id])
        add_text(relationship, "SuccessorProjectObjectId", 1)
        add_text(relationship, "Type", "Finish to Start")
        relationship_object_id += 1

    schedule_options = ET.SubElement(project, qname("ScheduleOptions"))
    add_text(schedule_options, "CalculateFloatBasedOnFinishDate", 1)
    add_text(schedule_options, "ComputeTotalFloatType", "Smallest of Start Float and Finish Float")
    add_text(schedule_options, "CriticalActivityFloatThreshold", 0)
    add_text(schedule_options, "CriticalActivityPathType", "Critical Float")
    add_text(schedule_options, "LevelAllResources", 1)
    add_text(schedule_options, "OutOfSequenceScheduleType", "Retained Logic")
    add_text(schedule_options, "PreserveScheduledEarlyAndLateDates", 1)
    add_text(schedule_options, "ProjectObjectId", 1)
    add_text(schedule_options, "UseExpectedFinishDates", 0)

    return ET.ElementTree(root)


if __name__ == "__main__":
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    tree = build_xml()
    ET.indent(tree, space="  ")
    tree.write(OUTPUT_XML_PATH, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {OUTPUT_XML_PATH.name}")
