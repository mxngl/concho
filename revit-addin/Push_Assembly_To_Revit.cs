using System;
using System.Collections.Generic;
using System.IO;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace QTO
{
    [Transaction(TransactionMode.Manual)]
    public class Push_Assembly_To_Revit : IExternalCommand
    {
        private const string MappingRelativePath = "Prefab_BIM_Mapper\\outputs\\Revit_Assembly_Id_Map.csv";
        private const string MappingFileName = "Revit_Assembly_Id_Map.csv";
        private const string ParameterName = "Prefab_Assembly_ID";

        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            try
            {
                Document doc = commandData.Application.ActiveUIDocument.Document;
                string mappingPath = CsvParameterPushHelper.ResolvePlanningOutputPath(MappingRelativePath);

                if (!File.Exists(mappingPath))
                {
                    TaskDialog.Show(
                        "Push Prefab Assembly IDs",
                        $"Could not find the mapping file:\n{mappingPath}\n\nRun the prefab pipeline first so {MappingFileName} exists."
                    );
                    return Result.Cancelled;
                }

                Dictionary<string, string> sourceToParameter = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                {
                    { "assembly_id", ParameterName },
                };

                CsvParameterPushHelper.AssignmentLoadResult loadResult =
                    CsvParameterPushHelper.LoadAssignments(mappingPath, "element_id", sourceToParameter);

                if (loadResult.Assignments.Count == 0)
                {
                    TaskDialog.Show(
                        "Push Prefab Assembly IDs",
                        $"No non-empty assembly assignments were found in:\n{mappingPath}"
                    );
                    return Result.Cancelled;
                }

                CsvParameterPushHelper.WriteResult writeResult =
                    CsvParameterPushHelper.WriteStringParametersToElements(doc, loadResult.Assignments);

                TaskDialog.Show(
                    "Push Prefab Assembly IDs",
                    CsvParameterPushHelper.BuildSummary(
                        mappingPath,
                        loadResult,
                        writeResult,
                        sourceToParameter.Values,
                        "Push Prefab Assembly IDs"
                    )
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
    }
}
