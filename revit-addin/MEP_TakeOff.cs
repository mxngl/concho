using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;

namespace QTO
{
    [Transaction(TransactionMode.Manual)]
    public class MEP_TakeOff : IExternalCommand
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
            "insulation",
            "lining",
            "flow",
            "airflow",
            "pressure",
            "capacity",
            "power",
            "voltage",
            "current",
            "load"
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

                IList<Element> mepElements = GetAllMepElements(doc);
                if (mepElements.Count == 0)
                {
                    TaskDialog.Show("Revit", "No MEP elements found in this model.");
                    return Result.Succeeded;
                }

                string? exportFolder = ExportPathHelper.GetExportFolder();
                if (exportFolder == null)
                    return Result.Cancelled;

                string csvPath = ExportPathHelper.GetScheduleFilePath(doc, exportFolder, "MEP_TakeOff");
                ExportSummary summary = ExportElementsToCsv(doc, mepElements, csvPath);

                summary.Show("MEP", csvPath);

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                TaskDialog.Show("Error", ex.ToString());
                return Result.Failed;
            }
        }

        private IList<Element> GetAllMepElements(Document doc)
        {
            List<BuiltInCategory> categories = new List<BuiltInCategory>
            {
                BuiltInCategory.OST_DuctCurves,
                BuiltInCategory.OST_DuctFitting,
                BuiltInCategory.OST_DuctAccessory,
                BuiltInCategory.OST_DuctTerminal,
                BuiltInCategory.OST_FlexDuctCurves,
                BuiltInCategory.OST_PipeCurves,
                BuiltInCategory.OST_PipeFitting,
                BuiltInCategory.OST_PipeAccessory,
                BuiltInCategory.OST_FlexPipeCurves,
                BuiltInCategory.OST_CableTray,
                BuiltInCategory.OST_CableTrayFitting,
                BuiltInCategory.OST_Conduit,
                BuiltInCategory.OST_ConduitFitting,
                BuiltInCategory.OST_PlumbingFixtures,
                BuiltInCategory.OST_MechanicalEquipment,
                BuiltInCategory.OST_ElectricalEquipment,
                BuiltInCategory.OST_ElectricalFixtures,
                BuiltInCategory.OST_LightingFixtures,
                BuiltInCategory.OST_Sprinklers
            };

            ElementMulticategoryFilter filter = new ElementMulticategoryFilter(categories);

            return new FilteredElementCollector(doc)
                .WherePasses(filter)
                .WhereElementIsNotElementType()
                .ToElements()
                .GroupBy(e => e.Id.Value)
                .Select(g => g.First())
                .ToList();
        }

        private ExportSummary ExportElementsToCsv(Document doc, IList<Element> elementsToExport, string filePath)
        {
            ExportSummary summary = new ExportSummary();
            bool metric = ParameterReader.IsMetric(doc, SpecTypeId.Length);
            StringBuilder csv = new StringBuilder();
            csv.AppendLine(
                "ElementId,Category,Family,Type,Level,Mark,System Name,System Type,Service Type,Classification,Size,Diameter,Width,Height,Length,Area,Volume,Material,Weight,Unit Weight,Insulation Thickness,Lining Thickness,Airflow,Flow,Pressure Drop,Cooling Capacity,Heating Capacity,Power,Voltage,Current,Apparent Load,Connected Load,Connector Count,Connector Flow,Connector Demand,Connector Max Diameter (in),Connector Max Width (in),Connector Max Height (in),Location Type,Position X (ft),Position Y (ft),Position Z (ft),Start X (ft),Start Y (ft),Start Z (ft),End X (ft),End Y (ft),End Z (ft),Rotation (deg),Bounding Box Min X (ft),Bounding Box Min Y (ft),Bounding Box Min Z (ft),Bounding Box Max X (ft),Bounding Box Max Y (ft),Bounding Box Max Z (ft),Bounding Box Center X (ft),Bounding Box Center Y (ft),Bounding Box Center Z (ft),Room Id,Room Number,Room Name,Room Level,Room Area (SF),Room Volume (CF),Room Location X (ft),Room Location Y (ft),Room Location Z (ft),Comments,Parameter Snapshot,Assembly Code,Category (local)"
            );

            foreach (Element elem in elementsToExport)
            {
                ConnectorMetrics connectorMetrics = GetConnectorMetrics(elem);
                SpatialElementData spatialData = SpatialElementData.FromElement(elem);
                RoomAssignmentData roomData = RoomAssignmentData.FromElement(doc, elem);

                string elementId = elem.Id.Value.ToString();
                string category = Categories.English(elem.Category);
                string categoryLocal = Categories.Local(elem.Category);
                string family = GetFamilyName(elem);
                string typeName = GetTypeName(doc, elem);
                string level = GetLevelName(doc, elem);
                string mark = ParameterReader.Text(doc, elem, new ParamCandidate("Mark", BuiltInParameter.ALL_MODEL_MARK));
                string systemName = ParameterReader.Text(doc, elem, new ParamCandidate("System Name", BuiltInParameter.RBS_SYSTEM_NAME_PARAM), "System");
                string systemType = GetFirstAvailableParameterValue(doc, elem, "System Type");
                string serviceType = GetFirstAvailableParameterValue(doc, elem, "Service Type");
                string classification = GetFirstAvailableParameterValue(
                    doc,
                    elem,
                    "Classification",
                    "Flow Classification",
                    "Part Type"
                );
                MepQuantities quantities = MepQuantities.Read(doc, elem);
                string size = BuildSize(doc, elem, quantities, connectorMetrics, metric, summary);
                string diameter = ParameterReader.Format(quantities.DiameterInches);
                string width = ParameterReader.Format(quantities.WidthInches);
                string height = ParameterReader.Format(quantities.HeightInches);
                // The one text column: fixed feet-inch format that the STV MEP importer parses (P4.5).
                string length = ParameterReader.FormatFeetInches(quantities.LengthFeet);
                string area = ParameterReader.Format(quantities.Area);
                string volume = ParameterReader.Format(quantities.Volume);
                string material = GetMaterialSummary(doc, elem);
                string weight = ParameterReader.Format(quantities.Weight);
                string unitWeight = ParameterReader.Format(quantities.UnitWeight);
                string insulationThickness = ParameterReader.Format(quantities.InsulationThicknessInches);
                string liningThickness = ParameterReader.Format(quantities.LiningThicknessInches);
                string airflow = ParameterReader.Format(quantities.Airflow);
                string flow = ParameterReader.Format(quantities.Flow);
                string pressureDrop = ParameterReader.Format(quantities.PressureDrop);
                string coolingCapacity = ParameterReader.Format(quantities.CoolingCapacity);
                string heatingCapacity = ParameterReader.Format(quantities.HeatingCapacity);
                string power = ParameterReader.Format(quantities.Power);
                string voltage = ParameterReader.Format(quantities.Voltage);
                string current = ParameterReader.Format(quantities.Current);
                string apparentLoad = ParameterReader.Format(quantities.ApparentLoad);
                string connectedLoad = ParameterReader.Format(quantities.ConnectedLoad);
                string comments = ParameterReader.Text(doc, elem, new ParamCandidate("Comments", BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS));
                string parameterSnapshot = BuildParameterSnapshot(doc, elem);
                // Last column (P4.3): appended so readers that use column positions keep working.
                string assemblyCode = ParameterReader.AssemblyCode(doc, elem);
                summary.Add(category, assemblyCode);
                summary.AddQuantities(category, quantities.LengthFeet, quantities.Area, quantities.Volume);
                if (metric && UsesSnapshotFallback(quantities, parameterSnapshot))
                    summary.SnapshotFallbackCount++;

                csv.AppendLine(string.Join(",",
                    EscapeCsv(elementId),
                    EscapeCsv(category),
                    EscapeCsv(family),
                    EscapeCsv(typeName),
                    EscapeCsv(level),
                    EscapeCsv(mark),
                    EscapeCsv(systemName),
                    EscapeCsv(systemType),
                    EscapeCsv(serviceType),
                    EscapeCsv(classification),
                    EscapeCsv(size),
                    EscapeCsv(diameter),
                    EscapeCsv(width),
                    EscapeCsv(height),
                    EscapeCsv(length),
                    EscapeCsv(area),
                    EscapeCsv(volume),
                    EscapeCsv(material),
                    EscapeCsv(weight),
                    EscapeCsv(unitWeight),
                    EscapeCsv(insulationThickness),
                    EscapeCsv(liningThickness),
                    EscapeCsv(airflow),
                    EscapeCsv(flow),
                    EscapeCsv(pressureDrop),
                    EscapeCsv(coolingCapacity),
                    EscapeCsv(heatingCapacity),
                    EscapeCsv(power),
                    EscapeCsv(voltage),
                    EscapeCsv(current),
                    EscapeCsv(apparentLoad),
                    EscapeCsv(connectedLoad),
                    EscapeCsv(connectorMetrics.Count.ToString(CultureInfo.InvariantCulture)),
                    EscapeCsv(Math.Abs(connectorMetrics.Flow) < 1e-9
                        ? ""
                        : ParameterReader.Format(UnitUtils.ConvertFromInternalUnits(connectorMetrics.Flow, UnitTypeId.CubicMetersPerSecond))),
                    EscapeCsv(FormatDouble(connectorMetrics.Demand)),
                    EscapeCsv(FormatDouble(connectorMetrics.MaxDiameterInches)),
                    EscapeCsv(FormatDouble(connectorMetrics.MaxWidthInches)),
                    EscapeCsv(FormatDouble(connectorMetrics.MaxHeightInches)),
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
                    EscapeCsv(assemblyCode),
                    EscapeCsv(categoryLocal)
                ));
            }

            File.WriteAllText(filePath, csv.ToString(), Encoding.UTF8);
            return summary;
        }

        /// <summary>
        /// Size in inches built from the numeric dimensions (<c>3"</c> or <c>4"x4"</c>), else from
        /// the largest connector. Without dimensions Revit's Size text is used, except in projects
        /// with metric sizes (STV would read millimetres as inches): then Size stays empty and the
        /// element is counted in the summary dialog.
        /// </summary>
        private static string BuildSize(
            Document doc,
            Element elem,
            MepQuantities quantities,
            ConnectorMetrics connectorMetrics,
            bool metricLength,
            ExportSummary summary)
        {
            if (quantities.DiameterInches > 0)
                return ParameterReader.FormatInchMark(quantities.DiameterInches.Value);

            if (quantities.WidthInches > 0 && quantities.HeightInches > 0)
                return ParameterReader.FormatInchMark(quantities.WidthInches.Value) + "x" +
                       ParameterReader.FormatInchMark(quantities.HeightInches.Value);

            if (connectorMetrics.MaxDiameterInches > 1e-9)
                return ParameterReader.FormatInchMark(connectorMetrics.MaxDiameterInches);

            if (connectorMetrics.MaxWidthInches > 1e-9 && connectorMetrics.MaxHeightInches > 1e-9)
                return ParameterReader.FormatInchMark(connectorMetrics.MaxWidthInches) + "x" +
                       ParameterReader.FormatInchMark(connectorMetrics.MaxHeightInches);

            string text = ParameterReader.Text(
                doc,
                elem,
                new ParamCandidate("Size", BuiltInParameter.RBS_CALCULATED_SIZE),
                "Nominal Size",
                "Overall Size"
            );
            if (string.IsNullOrWhiteSpace(text))
                return "";

            if (metricLength || ParameterReader.IsMetric(doc, SizeSpec(elem)))
            {
                summary.SizeLeftEmptyCount++;
                return "";
            }

            return text;
        }

        private static ForgeTypeId SizeSpec(Element elem)
        {
            long categoryId = elem.Category?.Id.Value ?? 0;
            if (categoryId == (long)BuiltInCategory.OST_DuctCurves ||
                categoryId == (long)BuiltInCategory.OST_DuctFitting ||
                categoryId == (long)BuiltInCategory.OST_DuctAccessory ||
                categoryId == (long)BuiltInCategory.OST_DuctTerminal ||
                categoryId == (long)BuiltInCategory.OST_FlexDuctCurves)
                return SpecTypeId.DuctSize;

            if (categoryId == (long)BuiltInCategory.OST_PipeCurves ||
                categoryId == (long)BuiltInCategory.OST_PipeFitting ||
                categoryId == (long)BuiltInCategory.OST_PipeAccessory ||
                categoryId == (long)BuiltInCategory.OST_FlexPipeCurves ||
                categoryId == (long)BuiltInCategory.OST_Sprinklers ||
                categoryId == (long)BuiltInCategory.OST_PlumbingFixtures)
                return SpecTypeId.PipeSize;

            if (categoryId == (long)BuiltInCategory.OST_CableTray ||
                categoryId == (long)BuiltInCategory.OST_CableTrayFitting)
                return SpecTypeId.CableTraySize;

            if (categoryId == (long)BuiltInCategory.OST_Conduit ||
                categoryId == (long)BuiltInCategory.OST_ConduitFitting)
                return SpecTypeId.ConduitSize;

            return SpecTypeId.Length;
        }

        /// <summary>
        /// True if STV would have to read a dimension, length or flow from the Parameter Snapshot
        /// (display text in project units) because the unit-safe main column is empty.
        /// </summary>
        private static bool UsesSnapshotFallback(MepQuantities quantities, string snapshot)
        {
            bool noDimensions = !quantities.DiameterInches.HasValue &&
                                !quantities.WidthInches.HasValue &&
                                !quantities.HeightInches.HasValue;
            if (noDimensions && SnapshotHas(snapshot, "Hydraulic Diameter", "Duct Width", "Duct Height"))
                return true;

            if (!quantities.LengthFeet.HasValue &&
                SnapshotHas(snapshot, "Length", "Duct Length", "Computed Length", "Length 1", "Duct Length 1"))
                return true;

            return !quantities.Airflow.HasValue && !quantities.Flow.HasValue &&
                   SnapshotHas(snapshot, "Supply Air Outlet Flow", "Supply Air Inlet Flow", "Return Air Inlet Flow", "Flow");
        }

        private static bool SnapshotHas(string snapshot, params string[] names)
        {
            return snapshot
                .Split(new[] { " | " }, StringSplitOptions.None)
                .Any(part => names.Any(name => part.StartsWith(name + "=", StringComparison.Ordinal)));
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

        private ConnectorMetrics GetConnectorMetrics(Element elem)
        {
            List<Connector> connectors = GetConnectors(elem);
            ConnectorMetrics metrics = new ConnectorMetrics();

            foreach (Connector connector in connectors)
            {
                metrics.Count += 1;
                metrics.Flow += SafeGetDouble(() => connector.Flow);
                metrics.Demand += SafeGetDouble(() => connector.Demand);
                metrics.MaxDiameterInches = Math.Max(
                    metrics.MaxDiameterInches,
                    SafeGetDouble(() => connector.Radius) * 24.0
                );
                metrics.MaxWidthInches = Math.Max(
                    metrics.MaxWidthInches,
                    SafeGetDouble(() => connector.Width) * 12.0
                );
                metrics.MaxHeightInches = Math.Max(
                    metrics.MaxHeightInches,
                    SafeGetDouble(() => connector.Height) * 12.0
                );
            }

            return metrics;
        }

        private List<Connector> GetConnectors(Element elem)
        {
            List<Connector> connectors = new List<Connector>();
            ConnectorSet? connectorSet = null;

            if (elem is MEPCurve mepCurve)
            {
                connectorSet = mepCurve.ConnectorManager?.Connectors;
            }
            else if (elem is FamilyInstance familyInstance && familyInstance.MEPModel != null)
            {
                connectorSet = familyInstance.MEPModel.ConnectorManager?.Connectors;
            }

            if (connectorSet == null)
                return connectors;

            foreach (Connector connector in connectorSet)
            {
                connectors.Add(connector);
            }

            return connectors;
        }

        private double SafeGetDouble(Func<double> getter)
        {
            try
            {
                return getter();
            }
            catch
            {
                return 0.0;
            }
        }

        private string FormatDouble(double value)
        {
            return Math.Abs(value) < 1e-9
                ? ""
                : value.ToString("0.###", CultureInfo.InvariantCulture);
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

        private class ConnectorMetrics
        {
            public int Count { get; set; }
            public double Flow { get; set; }
            public double Demand { get; set; }
            public double MaxDiameterInches { get; set; }
            public double MaxWidthInches { get; set; }
            public double MaxHeightInches { get; set; }
        }
    }
}




