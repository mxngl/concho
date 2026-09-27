using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using Autodesk.Revit.UI;

namespace QTO
{
    /// <summary>
    /// Assembly Code coverage of one export, shown in a TaskDialog after the export (P4.3).
    /// </summary>
    internal sealed class ExportSummary
    {
        private const int MaxCategoriesListed = 10;

        private readonly Dictionary<string, int> _missingByCategory =
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        public int ElementCount { get; private set; }
        public int WithAssemblyCode { get; private set; }

        public void Add(string category, string assemblyCode)
        {
            ElementCount++;
            if (!string.IsNullOrWhiteSpace(assemblyCode))
            {
                WithAssemblyCode++;
                return;
            }

            string key = string.IsNullOrWhiteSpace(category) ? "(no category)" : category;
            _missingByCategory[key] = _missingByCategory.TryGetValue(key, out int count) ? count + 1 : 1;
        }

        public string BuildText(string exportName, string csvPath)
        {
            CultureInfo culture = CultureInfo.InvariantCulture;
            int missing = ElementCount - WithAssemblyCode;
            double percent = ElementCount == 0 ? 0.0 : 100.0 * WithAssemblyCode / ElementCount;

            StringBuilder text = new StringBuilder();
            text.AppendLine(string.Format(culture, "{0}: {1:N0} elements exported to:", exportName, ElementCount));
            text.AppendLine(csvPath);
            text.AppendLine();
            text.AppendLine(string.Format(
                culture,
                "Assembly Code: {0:N0} of {1:N0} elements ({2:0.0} %)",
                WithAssemblyCode,
                ElementCount,
                percent
            ));

            if (missing == 0)
                return text.ToString().TrimEnd();

            text.AppendLine();
            text.AppendLine(string.Format(culture, "Missing Assembly Code ({0:N0} elements) by category:", missing));

            List<KeyValuePair<string, int>> ordered = _missingByCategory
                .OrderByDescending(kvp => kvp.Value)
                .ThenBy(kvp => kvp.Key, StringComparer.OrdinalIgnoreCase)
                .ToList();

            foreach (KeyValuePair<string, int> entry in ordered.Take(MaxCategoriesListed))
            {
                text.AppendLine(string.Format(culture, "  {0}: {1:N0}", entry.Key, entry.Value));
            }

            if (ordered.Count > MaxCategoriesListed)
            {
                List<KeyValuePair<string, int>> rest = ordered.Skip(MaxCategoriesListed).ToList();
                text.AppendLine(string.Format(
                    culture,
                    "  …and {0} more categories ({1:N0} elements)",
                    rest.Count,
                    rest.Sum(kvp => kvp.Value)
                ));
            }

            return text.ToString().TrimEnd();
        }

        public void Show(string exportName, string csvPath, string? extraText = null)
        {
            string content = BuildText(exportName, csvPath);
            if (!string.IsNullOrWhiteSpace(extraText))
                content += Environment.NewLine + Environment.NewLine + extraText;

            TaskDialog dialog = new TaskDialog("Concho export")
            {
                MainInstruction = string.Format(
                    CultureInfo.InvariantCulture,
                    "{0} export done: {1:0.0} % with Assembly Code",
                    exportName,
                    ElementCount == 0 ? 0.0 : 100.0 * WithAssemblyCode / ElementCount
                ),
                MainContent = content,
                FooterText = "Assembly Codes (Uniformat) are set in Revit under Type Properties → Identity Data. See docs/model-requirements.md."
            };
            dialog.Show();
        }
    }
}
