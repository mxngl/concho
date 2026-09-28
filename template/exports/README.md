# exports/

The Revit exports of the **Concho Revit add-in** (Add-Ins → External Tools). Put the CSV files
here exactly as the add-in writes them and push; the pipeline picks them up by file name.
Keep **only the latest export** of each model here (git keeps the history).

| Add-in command | File it writes | Used by (Tier 1) |
|---|---|---|
| Architecture TakeOff | `<model>_Architecture_TakeOff.csv` | TVD, STV |
| Architecture TakeOff | `<model>_Room_Boundaries.csv` | – (schedule, Tier 2; may stay here) |
| Structural TakeOff | `<model>_Structural_Schedule.csv` | TVD, STV |
| MEP TakeOff | `<model>_MEP_TakeOff.csv` | STV |

`<model>` is the Revit file name without extension. Several models are fine (e.g. an
architecture model and a structural model, each with its own exports):

```
exports/
  Team_ARCH_Architecture_TakeOff.csv
  Team_ARCH_Room_Boundaries.csv
  Team_STR_Structural_Schedule.csv
  Team_MEP_MEP_TakeOff.csv
```

Rules:

- **Don't rename** the files; the ending (`_Architecture_TakeOff.csv`, `_Structural_Schedule.csv`,
  `_MEP_TakeOff.csv`) tells the pipeline what a file is. Other CSV files are ignored with a
  warning.
- **Don't open and re-save them in Excel** (it changes the encoding and number format).
- Subfolders are read too, except folders named `raw/` (for anything you don't want the
  pipeline to read).
- The pipeline checks that each export has the columns it needs (`ElementId`, `Category`,
  `Assembly Code`); what the model must contain (Assembly Codes, units, `DNC` marker):
  [model requirements](https://github.com/mxngl/concho/blob/main/docs/model-requirements.md).
- STV reads all exports in **one run**, so an element that is in two exports (or a Revit part
  and its host) is counted once (decision D15). TVD takes one architecture and one structural
  file; with several, the pipeline joins them per discipline first.
