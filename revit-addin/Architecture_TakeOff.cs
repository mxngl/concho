using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace QTO
{
    [Transaction(TransactionMode.Manual)]
    public class Architecture_TakeOff : IExternalCommand
    {
        private static readonly string[] SnapshotKeywords =
        {
            "size",
            "diameter",
            "radius",
            "width",
            "height",
            "length",
            "area",
            "volume",
            "material",
            "weight",
            "mass",
            "thickness",
            "depth",
            "mark",
            "level",
            "offset",
            "comment",
            "assembly",
            "type",
            "fire",
            "finish"
        };

        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            try
            {
                UIDocument uidoc = commandData.Application.ActiveUIDocument;
                Document doc = uidoc.Document;

                IList<Element> architecturalElements = GetAllArchitecturalElements(doc);
                if (architecturalElements.Count == 0)
                {
                    TaskDialog.Show("Revit", "No architectural elements found in this model.");
                    return Result.Succeeded;
                }

                string? exportFolder = ExportPathHelper.GetExportFolder();
                if (exportFolder == null)
                    return Result.Cancelled;

                string csvPath = ExportPathHelper.GetScheduleFilePath(doc, exportFolder, "Architecture_TakeOff");
                ExportSummary summary = ExportElementsToCsv(doc, architecturalElements, csvPath);
                string roomBoundaryPath = ExportPathHelper.GetScheduleFilePath(doc, exportFolder, "Room_Boundaries");
                int roomCount = RoomBoundaryExporter.ExportRoomsToCsv(doc, roomBoundaryPath);

                summary.Show(
                    "Architecture",
                    csvPath,
                    $"Exported {roomCount} room boundaries to:\n{roomBoundaryPath}"
                );

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                TaskDialog.Show("Error", ex.ToString());
                return Result.Failed;
            }
        }

        private IList<Element> GetAllArchitecturalElements(Document doc)
        {
            List<BuiltInCategory> categories = new List<BuiltInCategory>
            {
                BuiltInCategory.OST_Walls,
                BuiltInCategory.OST_Doors,
                BuiltInCategory.OST_Windows,
                BuiltInCategory.OST_Floors,
                BuiltInCategory.OST_Roofs,
                BuiltInCategory.OST_Ceilings,
                BuiltInCategory.OST_Parts,
                BuiltInCategory.OST_CurtainWallPanels,
                BuiltInCategory.OST_CurtainWallMullions,
                BuiltInCategory.OST_Stairs,
                BuiltInCategory.OST_StairsRuns,
                BuiltInCategory.OST_StairsLandings,
                BuiltInCategory.OST_Railings,
                BuiltInCategory.OST_GenericModel,
                BuiltInCategory.OST_Casework,
                BuiltInCategory.OST_Furniture,
                BuiltInCategory.OST_FurnitureSystems,
                BuiltInCategory.OST_PlumbingFixtures
            };

            ElementMulticategoryFilter filter = new ElementMulticategoryFilter(categories);

            IList<Element> collectedElements = new FilteredElementCollector(doc)
                .WherePasses(filter)
                .WhereElementIsNotElementType()
                .ToElements()
                .GroupBy(e => e.Id.Value)
                .Select(g => g.First())
                .ToList();

            return collectedElements
                .Where(e => ShouldExportArchitecturalElement(doc, e))
                .ToList();
        }

        private bool ShouldExportArchitecturalElement(Document doc, Element elem)
        {
            if (IsPartElement(elem))
                return IsRelevantArchitecturalPart(elem, doc);

            if (IsCeilingElement(elem) && HasAssociatedParts(doc, elem))
                return false;

            return true;
        }

        private bool IsPartElement(Element elem)
        {
            return elem.Category != null
                && elem.Category.Id.Value == (long)BuiltInCategory.OST_Parts;
        }

        private bool IsCeilingElement(Element elem)
        {
            return elem.Category != null
                && elem.Category.Id.Value == (long)BuiltInCategory.OST_Ceilings;
        }

        private bool HasAssociatedParts(Document doc, Element elem)
        {
            try
            {
                ICollection<ElementId> associatedPartIds = PartUtils.GetAssociatedParts(
                    doc,
                    elem.Id,
                    true,
                    true
                );
                return associatedPartIds != null && associatedPartIds.Count > 0;
            }
            catch
            {
                return false;
            }
        }

        private bool IsRelevantArchitecturalPart(Element elem, Document doc)
        {
            string originalCategory = GetOriginalCategory(elem, doc);

            if (string.IsNullOrWhiteSpace(originalCategory))
                return false;

            string normalized = originalCategory.ToLowerInvariant();
            return normalized.Contains("ceiling");
        }

        private ExportSummary ExportElementsToCsv(Document doc, IList<Element> elementsToExport, string filePath)
        {
            ExportSummary summary = new ExportSummary();
            StringBuilder csv = new StringBuilder();
            csv.AppendLine(
                "ElementId,Category,Family,Type,Original Category,Original Family,Original Type,Level,Mark,Assembly Code,Assembly Description,Length,Width,Depth,Height,Area,Volume,Weight,Unit Weight,Material,Type Comments,Base Level,Top Level,Base Offset,Top Offset,Location Type,Position X (ft),Position Y (ft),Position Z (ft),Start X (ft),Start Y (ft),Start Z (ft),End X (ft),End Y (ft),End Z (ft),Rotation (deg),Bounding Box Min X (ft),Bounding Box Min Y (ft),Bounding Box Min Z (ft),Bounding Box Max X (ft),Bounding Box Max Y (ft),Bounding Box Max Z (ft),Bounding Box Center X (ft),Bounding Box Center Y (ft),Bounding Box Center Z (ft),Room Id,Room Number,Room Name,Room Level,Room Area (SF),Room Volume (CF),Room Location X (ft),Room Location Y (ft),Room Location Z (ft),Comments,Parameter Snapshot,Part Source Id,Category (local)"
            );

            foreach (Element elem in elementsToExport)
            {
                SpatialElementData spatialData = SpatialElementData.FromElement(elem);
                RoomAssignmentData roomData = RoomAssignmentData.FromElement(doc, elem);
                string elementId = elem.Id.Value.ToString();
                string category = Categories.English(elem.Category);
                string categoryLocal = Categories.Local(elem.Category);
                // Parts: Assembly Code of the source element; its id goes to "Part Source Id" (P4.5).
                Element? partSource = IsPartElement(elem) ? PartSource.SourceElement(doc, elem) : null;
                string partSourceId = partSource?.Id.Value.ToString() ?? "";
                string family = GetFamilyName(elem);
                string typeName = GetTypeName(doc, elem);
                string originalCategory = GetOriginalCategory(elem, doc);
                string originalFamily = GetOriginalPartValue(elem, doc, "Original Family", "Original Family Name");
                string originalType = GetOriginalPartValue(elem, doc, "Original Type", "Original Type Name");
                string level = GetLevelName(doc, elem);
                string mark = ParameterReader.Text(doc, elem, new ParamCandidate("Mark", BuiltInParameter.ALL_MODEL_MARK));
                string assemblyCode = partSource != null
                    ? ParameterReader.AssemblyCode(doc, partSource)
                    : "";
                if (string.IsNullOrWhiteSpace(assemblyCode))
                    assemblyCode = ParameterReader.AssemblyCode(doc, elem);
                string assemblyDescription = ParameterReader.AssemblyDescription(doc, elem);
                BuildingQuantities quantities = BuildingQuantities.Read(doc, elem);
                summary.Add(category, assemblyCode);
                summary.AddQuantities(category, quantities.Length, quantities.Area, quantities.Volume);
                string length = ParameterReader.Format(quantities.Length);
                string width = ParameterReader.Format(quantities.Width);
                string depth = ParameterReader.Format(quantities.Depth);
                string height = ParameterReader.Format(quantities.Height);
                string area = ParameterReader.Format(quantities.Area);
                string volume = ParameterReader.Format(quantities.Volume);
                string weight = ParameterReader.Format(quantities.Weight);
                string unitWeight = ParameterReader.Format(quantities.UnitWeight);
                string material = GetMaterialSummary(doc, elem);
                string typeComments = GetTypeParameterValue(doc, elem, "Type Comments");
                string baseLevel = GetFirstAvailableParameterValue(doc, elem, "Base Level");
                string topLevel = GetFirstAvailableParameterValue(doc, elem, "Top Level");
                string baseOffset = ParameterReader.Format(quantities.BaseOffset);
                string topOffset = ParameterReader.Format(quantities.TopOffset);
                string comments = ParameterReader.Text(doc, elem, new ParamCandidate("Comments", BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS));
                string parameterSnapshot = BuildParameterSnapshot(doc, elem);

                csv.AppendLine(string.Join(",",
                    EscapeCsv(elementId),
                    EscapeCsv(category),
                    EscapeCsv(family),
                    EscapeCsv(typeName),
                    EscapeCsv(originalCategory),
                    EscapeCsv(originalFamily),
                    EscapeCsv(originalType),
                    EscapeCsv(level),
                    EscapeCsv(mark),
                    EscapeCsv(assemblyCode),
                    EscapeCsv(assemblyDescription),
                    EscapeCsv(length),
                    EscapeCsv(width),
                    EscapeCsv(depth),
                    EscapeCsv(height),
                    EscapeCsv(area),
                    EscapeCsv(volume),
                    EscapeCsv(weight),
                    EscapeCsv(unitWeight),
                    EscapeCsv(material),
                    EscapeCsv(typeComments),
                    EscapeCsv(baseLevel),
                    EscapeCsv(topLevel),
                    EscapeCsv(baseOffset),
                    EscapeCsv(topOffset),
                    EscapeCsv(spatialData.LocationType),
                    EscapeCsv(spatialData.PositionXFeet),
                    EscapeCsv(spatialData.PositionYFeet),
                    EscapeCsv(spatialData.PositionZFeet),
                    EscapeCsv(spatialData.StartXFeet),
                    EscapeCsv(spatialData.StartYFeet),
                    EscapeCsv(spatialData.StartZFeet),
                    EscapeCsv(spatialData.EndXFeet),
                    EscapeCsv(spatialData.EndYFeet),
                    EscapeCsv(spatialData.EndZFeet),
                    EscapeCsv(spatialData.RotationDegrees),
                    EscapeCsv(spatialData.BoundingBoxMinXFeet),
                    EscapeCsv(spatialData.BoundingBoxMinYFeet),
                    EscapeCsv(spatialData.BoundingBoxMinZFeet),
                    EscapeCsv(spatialData.BoundingBoxMaxXFeet),
                    EscapeCsv(spatialData.BoundingBoxMaxYFeet),
                    EscapeCsv(spatialData.BoundingBoxMaxZFeet),
                    EscapeCsv(spatialData.BoundingBoxCenterXFeet),
                    EscapeCsv(spatialData.BoundingBoxCenterYFeet),
                    EscapeCsv(spatialData.BoundingBoxCenterZFeet),
                    EscapeCsv(roomData.RoomId),
                    EscapeCsv(roomData.RoomNumber),
                    EscapeCsv(roomData.RoomName),
                    EscapeCsv(roomData.RoomLevel),
                    EscapeCsv(roomData.RoomAreaSquareFeet),
                    EscapeCsv(roomData.RoomVolumeCubicFeet),
                    EscapeCsv(roomData.RoomLocationXFeet),
                    EscapeCsv(roomData.RoomLocationYFeet),
                    EscapeCsv(roomData.RoomLocationZFeet),
                    EscapeCsv(comments),
                    EscapeCsv(parameterSnapshot),
                    EscapeCsv(partSourceId),
                    EscapeCsv(categoryLocal)
                ));
            }

            File.WriteAllText(filePath, csv.ToString(), Encoding.UTF8);
            return summary;
        }

        private string BuildParameterSnapshot(Document doc, Element elem)
        {
            Dictionary<string, string> values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            foreach (Parameter parameter in elem.Parameters.Cast<Parameter>())
            {
                AddSnapshotValue(values, parameter, doc);
            }

            ElementId typeId = elem.GetTypeId();
            if (typeId != ElementId.InvalidElementId)
            {
                Element? typeElem = doc.GetElement(typeId);
                if (typeElem != null)
                {
                    foreach (Parameter parameter in typeElem.Parameters.Cast<Parameter>())
                    {
                        AddSnapshotValue(values, parameter, doc);
                    }
                }
            }

            return string.Join(
                " | ",
                values
                    .OrderBy(kvp => kvp.Key, StringComparer.OrdinalIgnoreCase)
                    .Select(kvp => $"{kvp.Key}={kvp.Value}")
            );
        }

        private void AddSnapshotValue(Dictionary<string, string> values, Parameter parameter, Document doc)
        {
            string name = parameter.Definition?.Name ?? "";
            if (string.IsNullOrWhiteSpace(name))
                return;

            string lowered = name.ToLowerInvariant();
            if (!SnapshotKeywords.Any(keyword => lowered.Contains(keyword)))
                return;

            string value = GetParameterValue(parameter, doc);
            if (string.IsNullOrWhiteSpace(value))
                return;

            values.TryAdd(name, value);
        }

        private string GetFamilyName(Element elem)
        {
            if (elem is FamilyInstance fi && fi.Symbol?.Family != null)
            {
                return fi.Symbol.Family.Name;
            }

            return "";
        }

        private string GetTypeName(Document doc, Element elem)
        {
            ElementId typeId = elem.GetTypeId();
            if (typeId != ElementId.InvalidElementId)
            {
                Element typeElem = doc.GetElement(typeId);
                return typeElem?.Name ?? "";
            }

            return "";
        }

        /// <summary>
        /// English category of the element a part was divided from (language-independent, P4.5);
        /// the "Original Category" parameter text only if the source can't be resolved.
        /// </summary>
        private string GetOriginalCategory(Element elem, Document doc)
        {
            if (!IsPartElement(elem))
                return "";

            Element? source = PartSource.SourceElement(doc, elem);
            if (source != null)
                return Categories.English(source.Category);

            return GetOriginalPartValue(elem, doc, "Original Category", "Original Category Id", "Part Original Category");
        }

        private string GetOriginalPartValue(Element elem, Document doc, params string[] parameterNames)
        {
            if (!IsPartElement(elem))
                return "";

            foreach (string parameterName in parameterNames)
            {
                string value = GetParameterValue(elem.LookupParameter(parameterName), doc);
                if (!string.IsNullOrWhiteSpace(value))
                    return value;
            }

            return "";
        }

        private string GetLevelName(Document doc, Element elem)
        {
            Parameter levelParam = elem.LookupParameter("Level");
            if (levelParam != null)
            {
                return GetParameterValue(levelParam, doc);
            }

            if (elem.LevelId != ElementId.InvalidElementId)
            {
                Element levelElem = doc.GetElement(elem.LevelId);
                return levelElem?.Name ?? "";
            }

            return "";
        }

        private string GetFirstAvailableParameterValue(Document doc, Element elem, params string[] parameterNames)
        {
            foreach (string parameterName in parameterNames)
            {
                string value = GetParameterValue(elem.LookupParameter(parameterName), doc);
                if (!string.IsNullOrWhiteSpace(value))
                    return value;

                ElementId typeId = elem.GetTypeId();
                if (typeId == ElementId.InvalidElementId)
                    continue;

                Element? typeElem = doc.GetElement(typeId);
                if (typeElem == null)
                    continue;

                value = GetParameterValue(typeElem.LookupParameter(parameterName), doc);
                if (!string.IsNullOrWhiteSpace(value))
                    return value;
            }

            return "";
        }

        private string GetTypeParameterValue(Document doc, Element elem, string parameterName)
        {
            ElementId typeId = elem.GetTypeId();
            if (typeId == ElementId.InvalidElementId)
                return "";

            Element typeElem = doc.GetElement(typeId);
            if (typeElem == null)
                return "";

            return GetParameterValue(typeElem.LookupParameter(parameterName), doc);
        }

        private string GetMaterialSummary(Document doc, Element elem)
        {
            ICollection<ElementId> materialIds = elem.GetMaterialIds(false);
            if (materialIds == null || materialIds.Count == 0)
                return "";

            return string.Join("; ",
                materialIds
                    .Select(doc.GetElement)
                    .OfType<Material>()
                    .Select(material => material.Name)
                    .Distinct()
            );
        }

        private string GetParameterValue(Parameter para, Document document)
        {
            if (para == null)
                return "";

            try
            {
                switch (para.StorageType)
                {
                    case StorageType.Double:
                        return para.AsValueString() ?? "";

                    case StorageType.ElementId:
                        ElementId id = para.AsElementId();
                        if (id == ElementId.InvalidElementId)
                            return "";

                        if (id.Value >= 0)
                        {
                            Element referencedElem = document.GetElement(id);
                            return referencedElem?.Name ?? id.Value.ToString();
                        }

                        return id.Value.ToString();

                    case StorageType.Integer:
                        if (para.Definition != null &&
                            para.Definition.GetDataType() == SpecTypeId.Boolean.YesNo)
                        {
                            return para.AsInteger() == 0 ? "False" : "True";
                        }

                        return para.AsInteger().ToString();

                    case StorageType.String:
                        return para.AsString() ?? "";

                    case StorageType.None:
                    default:
                        return "";
                }
            }
            catch
            {
                return "";
            }
        }

        private string EscapeCsv(string value)
        {
            if (value == null)
                return "";

            value = value.Replace("\"", "\"\"");

            if (value.Contains(",") || value.Contains("\"") || value.Contains("\n") || value.Contains("\r"))
            {
                return $"\"{value}\"";
            }

            return value;
        }
    }
}




