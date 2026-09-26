using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;

namespace QTO
{
    internal static class CsvParameterPushHelper
    {
        internal static string ResolvePlanningOutputPath(string relativePathFromPlanningEngine)
        {
            string assemblyDirectory = Path.GetDirectoryName(
                System.Reflection.Assembly.GetExecutingAssembly().Location
            ) ?? "";

            DirectoryInfo directory = new DirectoryInfo(assemblyDirectory);
            while (directory != null &&
                   !Directory.Exists(Path.Combine(directory.FullName, "src", "Planning_engine")))
            {
                directory = directory.Parent;
            }

            string planningDirectory = directory != null
                ? Path.Combine(directory.FullName, "src", "Planning_engine")
                : Path.Combine(assemblyDirectory, "src", "Planning_engine");

            return Path.Combine(planningDirectory, relativePathFromPlanningEngine);
        }

        internal static List<Dictionary<string, string>> LoadCsvRows(string csvPath)
        {
            using StreamReader reader = new StreamReader(csvPath);
            string headerLine = reader.ReadLine();
            if (string.IsNullOrWhiteSpace(headerLine))
            {
                throw new InvalidOperationException($"The mapping file is empty: {csvPath}");
            }

            List<string> headers = ParseCsvLine(headerLine);
            List<Dictionary<string, string>> rows = new List<Dictionary<string, string>>();

            while (!reader.EndOfStream)
            {
                string line = reader.ReadLine();
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                List<string> fields = ParseCsvLine(line);
                Dictionary<string, string> row = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                for (int i = 0; i < headers.Count; i++)
                {
                    string value = i < fields.Count ? fields[i].Trim() : "";
                    row[headers[i]] = value;
                }

                rows.Add(row);
            }

            return rows;
        }

        internal static AssignmentLoadResult LoadAssignments(
            string csvPath,
            string elementIdColumn,
            IReadOnlyDictionary<string, string> sourceToParameterMap)
        {
            List<Dictionary<string, string>> rows = LoadCsvRows(csvPath);
            Dictionary<int, Dictionary<string, HashSet<string>>> valuesByElement =
                new Dictionary<int, Dictionary<string, HashSet<string>>>();

            int invalidElementIdCount = 0;
            int blankValueCount = 0;

            foreach (Dictionary<string, string> row in rows)
            {
                if (!row.TryGetValue(elementIdColumn, out string elementIdText) ||
                    !int.TryParse(elementIdText, out int elementId))
                {
                    invalidElementIdCount++;
                    continue;
                }

                if (!valuesByElement.TryGetValue(elementId, out Dictionary<string, HashSet<string>> parameterValues))
                {
                    parameterValues = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
                    valuesByElement[elementId] = parameterValues;
                }

                foreach (KeyValuePair<string, string> pair in sourceToParameterMap)
                {
                    if (!row.TryGetValue(pair.Key, out string value) || string.IsNullOrWhiteSpace(value))
                    {
                        blankValueCount++;
                        continue;
                    }

                    if (!parameterValues.TryGetValue(pair.Value, out HashSet<string> values))
                    {
                        values = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                        parameterValues[pair.Value] = values;
                    }

                    values.Add(value.Trim());
                }
            }

            Dictionary<int, Dictionary<string, string>> assignments =
                new Dictionary<int, Dictionary<string, string>>();
            int conflictingValueCount = 0;

            foreach (KeyValuePair<int, Dictionary<string, HashSet<string>>> elementPair in valuesByElement)
            {
                Dictionary<string, string> elementAssignments = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                bool hasConflict = false;

                foreach (KeyValuePair<string, HashSet<string>> parameterPair in elementPair.Value)
                {
                    if (parameterPair.Value.Count == 1)
                    {
                        elementAssignments[parameterPair.Key] = parameterPair.Value.First();
                    }
                    else if (parameterPair.Value.Count > 1)
                    {
                        hasConflict = true;
                    }
                }

                if (hasConflict)
                {
                    conflictingValueCount++;
                    continue;
                }

                if (elementAssignments.Count > 0)
                {
                    assignments[elementPair.Key] = elementAssignments;
                }
            }

            return new AssignmentLoadResult(assignments, invalidElementIdCount, blankValueCount, conflictingValueCount);
        }

        internal static WriteResult WriteStringParametersToElements(
            Document doc,
            IReadOnlyDictionary<int, Dictionary<string, string>> assignments)
        {
            int updatedCount = 0;
            int unchangedCount = 0;
            int missingElementCount = 0;
            int missingParameterCount = 0;
            int readOnlyParameterCount = 0;
            int incompatibleParameterCount = 0;

            using Transaction transaction = new Transaction(doc, "Push prefab parameters to Revit");
            transaction.Start();

            foreach (KeyValuePair<int, Dictionary<string, string>> assignment in assignments)
            {
                Element element = doc.GetElement(new ElementId(assignment.Key));
                if (element == null)
                {
                    missingElementCount++;
                    continue;
                }

                foreach (KeyValuePair<string, string> parameterAssignment in assignment.Value)
                {
                    Parameter parameter = element.LookupParameter(parameterAssignment.Key);
                    if (parameter == null)
                    {
                        missingParameterCount++;
                        continue;
                    }

                    if (parameter.IsReadOnly)
                    {
                        readOnlyParameterCount++;
                        continue;
                    }

                    if (parameter.StorageType != StorageType.String)
                    {
                        incompatibleParameterCount++;
                        continue;
                    }

                    string currentValue = parameter.AsString() ?? string.Empty;
                    if (string.Equals(currentValue, parameterAssignment.Value, StringComparison.Ordinal))
                    {
                        unchangedCount++;
                        continue;
                    }

                    parameter.Set(parameterAssignment.Value);
                    updatedCount++;
                }
            }

            transaction.Commit();

            return new WriteResult(
                updatedCount,
                unchangedCount,
                missingElementCount,
                missingParameterCount,
                readOnlyParameterCount,
                incompatibleParameterCount
            );
        }

        internal static string BuildSummary(
            string mappingPath,
            AssignmentLoadResult loadResult,
            WriteResult writeResult,
            IEnumerable<string> targetParameters,
            string title)
        {
            StringBuilder summary = new StringBuilder();
            summary.AppendLine($"Source: {mappingPath}");
            summary.AppendLine($"Target parameters: {string.Join(", ", targetParameters)}");
            summary.AppendLine();
            summary.AppendLine($"Elements loaded: {loadResult.Assignments.Count}");
            summary.AppendLine($"Parameter values updated: {writeResult.UpdatedCount}");
            summary.AppendLine($"Parameter values already up to date: {writeResult.UnchangedCount}");
            summary.AppendLine($"Elements not found in model: {writeResult.MissingElementCount}");
            summary.AppendLine($"Missing parameters: {writeResult.MissingParameterCount}");
            summary.AppendLine($"Read-only parameters: {writeResult.ReadOnlyParameterCount}");
            summary.AppendLine($"Non-text parameters: {writeResult.IncompatibleParameterCount}");

            if (loadResult.BlankValueCount > 0)
            {
                summary.AppendLine($"Skipped blank source values: {loadResult.BlankValueCount}");
            }

            if (loadResult.InvalidElementIdCount > 0)
            {
                summary.AppendLine($"Skipped invalid element ids: {loadResult.InvalidElementIdCount}");
            }

            if (loadResult.ConflictingValueCount > 0)
            {
                summary.AppendLine($"Skipped elements with conflicting source values: {loadResult.ConflictingValueCount}");
            }

            if (writeResult.MissingParameterCount > 0 ||
                writeResult.ReadOnlyParameterCount > 0 ||
                writeResult.IncompatibleParameterCount > 0)
            {
                summary.AppendLine();
                summary.AppendLine($"{title}: make sure the target shared parameters exist and are editable text parameters.");
            }

            return summary.ToString().TrimEnd();
        }

        private static List<string> ParseCsvLine(string line)
        {
            List<string> fields = new List<string>();
            StringBuilder current = new StringBuilder();
            bool inQuotes = false;

            for (int i = 0; i < line.Length; i++)
            {
                char c = line[i];

                if (c == '"')
                {
                    if (inQuotes && i + 1 < line.Length && line[i + 1] == '"')
                    {
                        current.Append('"');
                        i++;
                    }
                    else
                    {
                        inQuotes = !inQuotes;
                    }

                    continue;
                }

                if (c == ',' && !inQuotes)
                {
                    fields.Add(current.ToString());
                    current.Clear();
                    continue;
                }

                current.Append(c);
            }

            fields.Add(current.ToString());
            return fields;
        }

        internal sealed class AssignmentLoadResult
        {
            internal AssignmentLoadResult(
                Dictionary<int, Dictionary<string, string>> assignments,
                int invalidElementIdCount,
                int blankValueCount,
                int conflictingValueCount)
            {
                Assignments = assignments;
                InvalidElementIdCount = invalidElementIdCount;
                BlankValueCount = blankValueCount;
                ConflictingValueCount = conflictingValueCount;
            }

            internal Dictionary<int, Dictionary<string, string>> Assignments { get; }
            internal int InvalidElementIdCount { get; }
            internal int BlankValueCount { get; }
            internal int ConflictingValueCount { get; }
        }

        internal sealed class WriteResult
        {
            internal WriteResult(
                int updatedCount,
                int unchangedCount,
                int missingElementCount,
                int missingParameterCount,
                int readOnlyParameterCount,
                int incompatibleParameterCount)
            {
                UpdatedCount = updatedCount;
                UnchangedCount = unchangedCount;
                MissingElementCount = missingElementCount;
                MissingParameterCount = missingParameterCount;
                ReadOnlyParameterCount = readOnlyParameterCount;
                IncompatibleParameterCount = incompatibleParameterCount;
            }

            internal int UpdatedCount { get; }
            internal int UnchangedCount { get; }
            internal int MissingElementCount { get; }
            internal int MissingParameterCount { get; }
            internal int ReadOnlyParameterCount { get; }
            internal int IncompatibleParameterCount { get; }
        }
    }
}
