using System;
using System.Collections.Generic;
using System.IO;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace QTO
{
    [Transaction(TransactionMode.Manual)]
    public class Push_Kit_To_Revit : IExternalCommand
    {
        private const string MappingRelativePath = "Prefab_BIM_Mapper\\outputs\\Revit_Kit_Parameter_Map.csv";
        private const string MappingFileName = "Revit_Kit_Parameter_Map.csv";

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
                        "Push Prefab Kit Parameters",
                        $"Could not find the mapping file:\n{mappingPath}\n\nRun the prefab kit pipeline first so {MappingFileName} exists."
                    );
                    return Result.Cancelled;
                }

                Dictionary<string, string> sourceToParameter = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                {
                    { "kit_id", "Prefab_Kit_ID" },
                };

                CsvParameterPushHelper.AssignmentLoadResult loadResult =
                    CsvParameterPushHelper.LoadAssignments(mappingPath, "element_id", sourceToParameter);

                if (loadResult.Assignments.Count == 0)
                {
                    TaskDialog.Show(
                        "Push Prefab Kit Parameters",
                        $"No non-empty kit parameter assignments were found in:\n{mappingPath}"
                    );
                    return Result.Cancelled;
                }

                CsvParameterPushHelper.WriteResult writeResult =
                    CsvParameterPushHelper.WriteStringParametersToElements(doc, loadResult.Assignments);

                TaskDialog.Show(
                    "Push Prefab Kit Parameters",
                    CsvParameterPushHelper.BuildSummary(
                        mappingPath,
                        loadResult,
                        writeResult,
                        sourceToParameter.Values,
                        "Push Prefab Kit Parameters"
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
