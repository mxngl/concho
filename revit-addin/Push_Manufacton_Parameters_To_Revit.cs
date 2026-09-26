using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace QTO
{
    [Transaction(TransactionMode.Manual)]
    public class Push_Manufacton_Parameters_To_Revit : IExternalCommand
    {
        private const string AssemblyMappingRelativePath = "Prefab_BIM_Mapper\\outputs\\Revit_Assembly_Id_Map.csv";
        private const string KitMappingRelativePath = "Prefab_BIM_Mapper\\outputs\\Revit_Kit_Parameter_Map.csv";

        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            try
            {
                Document doc = commandData.Application.ActiveUIDocument.Document;

                string assemblyMappingPath = CsvParameterPushHelper.ResolvePlanningOutputPath(AssemblyMappingRelativePath);
                string kitMappingPath = CsvParameterPushHelper.ResolvePlanningOutputPath(KitMappingRelativePath);

                if (!File.Exists(assemblyMappingPath) && !File.Exists(kitMappingPath))
                {
                    TaskDialog.Show(
                        "Push Manufacton Parameters",
                        "Could not find either Manufacton mapping file.\n\n" +
                        $"Assembly map:\n{assemblyMappingPath}\n\n" +
                        $"Kit map:\n{kitMappingPath}\n\n" +
                        "Run the prefab pipeline first so the Revit push maps exist."
                    );
                    return Result.Cancelled;
                }

                Dictionary<int, Dictionary<string, string>> mergedAssignments =
                    new Dictionary<int, Dictionary<string, string>>();
                List<string> summarySections = new List<string>();
                HashSet<string> targetParameters = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

                if (File.Exists(assemblyMappingPath))
                {
                    Dictionary<string, string> assemblySourceToParameter = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        { "assembly_id", "Prefab_Assembly_ID" },
                        { "catalog_id", "Prefab_Catalog_ID" },
                    };

                    CsvParameterPushHelper.AssignmentLoadResult assemblyLoadResult =
                        CsvParameterPushHelper.LoadAssignments(assemblyMappingPath, "element_id", assemblySourceToParameter);

                    MergeAssignments(mergedAssignments, assemblyLoadResult.Assignments);
                    foreach (string parameterName in assemblySourceToParameter.Values)
                    {
                        targetParameters.Add(parameterName);
                    }

                    summarySections.Add(
                        BuildLoadSection("Assembly map", assemblyMappingPath, assemblyLoadResult, assemblySourceToParameter.Values)
                    );
                }

                if (File.Exists(kitMappingPath))
                {
                    Dictionary<string, string> kitSourceToParameter = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        { "kit_id", "Prefab_Kit_ID" },
                        { "order_id", "Prefab_order_ID" },
                        { "item_name", "Prefab_Item_Name" },
                    };

                    CsvParameterPushHelper.AssignmentLoadResult kitLoadResult =
                        CsvParameterPushHelper.LoadAssignments(kitMappingPath, "element_id", kitSourceToParameter);

                    MergeAssignments(mergedAssignments, kitLoadResult.Assignments);
                    foreach (string parameterName in kitSourceToParameter.Values)
                    {
                        targetParameters.Add(parameterName);
                    }

                    summarySections.Add(
                        BuildLoadSection("Kit map", kitMappingPath, kitLoadResult, kitSourceToParameter.Values)
                    );
                }

                if (mergedAssignments.Count == 0)
                {
                    TaskDialog.Show(
                        "Push Manufacton Parameters",
                        "No non-empty Manufacton assignments were found in the available mapping files."
                    );
                    return Result.Cancelled;
                }

                CsvParameterPushHelper.WriteResult writeResult =
                    CsvParameterPushHelper.WriteStringParametersToElements(doc, mergedAssignments);

                StringBuilder summary = new StringBuilder();
                summary.AppendLine("Push Manufacton Parameters");
                summary.AppendLine();
                foreach (string section in summarySections)
                {
                    summary.AppendLine(section);
                    summary.AppendLine();
                }

                summary.AppendLine($"Elements loaded: {mergedAssignments.Count}");
                summary.AppendLine($"Target parameters: {string.Join(", ", targetParameters.OrderBy(name => name))}");
                summary.AppendLine($"Parameter values updated: {writeResult.UpdatedCount}");
                summary.AppendLine($"Parameter values already up to date: {writeResult.UnchangedCount}");
                summary.AppendLine($"Elements not found in model: {writeResult.MissingElementCount}");
                summary.AppendLine($"Missing parameters: {writeResult.MissingParameterCount}");
                summary.AppendLine($"Read-only parameters: {writeResult.ReadOnlyParameterCount}");
                summary.AppendLine($"Non-text parameters: {writeResult.IncompatibleParameterCount}");

                if (writeResult.MissingParameterCount > 0 ||
                    writeResult.ReadOnlyParameterCount > 0 ||
                    writeResult.IncompatibleParameterCount > 0)
                {
                    summary.AppendLine();
                    summary.AppendLine(
                        "Make sure Prefab_Assembly_ID, Prefab_Catalog_ID, Prefab_Kit_ID, Prefab_order_ID, and Prefab_Item_Name exist on the target categories as editable text parameters."
                    );
                }

                TaskDialog.Show("Push Manufacton Parameters", summary.ToString().TrimEnd());
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                TaskDialog.Show("Error", ex.ToString());
                return Result.Failed;
            }
        }

        private static void MergeAssignments(
            Dictionary<int, Dictionary<string, string>> mergedAssignments,
            IReadOnlyDictionary<int, Dictionary<string, string>> incomingAssignments)
        {
            foreach (KeyValuePair<int, Dictionary<string, string>> elementAssignment in incomingAssignments)
            {
                if (!mergedAssignments.TryGetValue(elementAssignment.Key, out Dictionary<string, string> parameterAssignments))
                {
                    parameterAssignments = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    mergedAssignments[elementAssignment.Key] = parameterAssignments;
                }

                foreach (KeyValuePair<string, string> parameterAssignment in elementAssignment.Value)
                {
                    parameterAssignments[parameterAssignment.Key] = parameterAssignment.Value;
                }
            }
        }

        private static string BuildLoadSection(
            string label,
            string mappingPath,
            CsvParameterPushHelper.AssignmentLoadResult loadResult,
            IEnumerable<string> targetParameters)
        {
            StringBuilder summary = new StringBuilder();
            summary.AppendLine($"{label}:");
            summary.AppendLine($"  Source: {mappingPath}");
            summary.AppendLine($"  Target parameters: {string.Join(", ", targetParameters)}");
            summary.AppendLine($"  Elements loaded: {loadResult.Assignments.Count}");

            if (loadResult.BlankValueCount > 0)
            {
                summary.AppendLine($"  Skipped blank source values: {loadResult.BlankValueCount}");
            }

            if (loadResult.InvalidElementIdCount > 0)
            {
                summary.AppendLine($"  Skipped invalid element ids: {loadResult.InvalidElementIdCount}");
            }

            if (loadResult.ConflictingValueCount > 0)
            {
                summary.AppendLine($"  Skipped conflicting source values: {loadResult.ConflictingValueCount}");
            }

            return summary.ToString().TrimEnd();
        }
    }
}
