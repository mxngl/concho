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

        private readonly Dictionary<string, int> _noQuantityByCategory =
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        private readonly Dictionary<string, Dictionary<string, int>> _missingQuantityByCategory =
            new Dictionary<string, Dictionary<string, int>>
            {
                { "Length", new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase) },
                { "Area", new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase) },
                { "Volume", new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase) }
            };

        public int ElementCount { get; private set; }
        public int WithAssemblyCode { get; private set; }

        // P4.5: quantities that stayed empty after the built-in parameter and name lookups.
        public int MissingLength { get; private set; }
        public int MissingArea { get; private set; }
        public int MissingVolume { get; private set; }
        public int WithoutAnyQuantity { get; private set; }

        /// <summary>MEP, metric sizes: elements without dimensions whose Size was left empty.</summary>
        public int SizeLeftEmptyCount { get; set; }

        /// <summary>MEP, metric project: elements where STV would fall back to the Parameter Snapshot.</summary>
        public int SnapshotFallbackCount { get; set; }

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

        public void AddQuantities(string category, double? length, double? area, double? volume)
        {
            string key = string.IsNullOrWhiteSpace(category) ? "(no category)" : category;
            if (!length.HasValue)
            {
                MissingLength++;
                Increment(_missingQuantityByCategory["Length"], key);
            }
            if (!area.HasValue)
            {
                MissingArea++;
                Increment(_missingQuantityByCategory["Area"], key);
            }
            if (!volume.HasValue)
            {
                MissingVolume++;
                Increment(_missingQuantityByCategory["Volume"], key);
            }
            if (length.HasValue || area.HasValue || volume.HasValue)
                return;

            WithoutAnyQuantity++;
            Increment(_noQuantityByCategory, key);
        }

        private static void Increment(Dictionary<string, int> counts, string key)
        {
            counts[key] = counts.TryGetValue(key, out int count) ? count + 1 : 1;
        }

        /// <summary>"Walls 12, Doors 3, …" for the top categories.</summary>
        private static string TopCategories(Dictionary<string, int> counts, CultureInfo culture, int top)
        {
            string listed = string.Join(", ", counts
                .OrderByDescending(kvp => kvp.Value)
                .ThenBy(kvp => kvp.Key, StringComparer.OrdinalIgnoreCase)
                .Take(top)
                .Select(kvp => string.Format(culture, "{0} {1:N0}", kvp.Key, kvp.Value)));
            return counts.Count > top ? listed + ", \u2026" : listed;
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

            AppendQuantityText(text, culture);

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

        private void AppendQuantityText(StringBuilder text, CultureInfo culture)
        {
            text.AppendLine();
            text.AppendLine("Quantity not found (left empty), top categories:");
            foreach (KeyValuePair<string, Dictionary<string, int>> entry in _missingQuantityByCategory)
            {
                int total = entry.Value.Values.Sum();
                text.AppendLine(total == 0
                    ? string.Format(culture, "  {0}: none", entry.Key)
                    : string.Format(
                        culture,
                        "  {0}: {1:N0} ({2})",
                        entry.Key,
                        total,
                        TopCategories(entry.Value, culture, 5)
                    ));
            }

            if (WithoutAnyQuantity > 0)
            {
                text.AppendLine(string.Format(
                    culture,
                    "  none of the three: {0:N0} ({1})",
                    WithoutAnyQuantity,
                    TopCategories(_noQuantityByCategory, culture, 5)
                ));
            }

            if (SizeLeftEmptyCount > 0)
            {
                text.AppendLine(string.Format(
                    culture,
                    "{0:N0} MEP elements without dimensions, Size left empty (metric sizes)",
                    SizeLeftEmptyCount
                ));
            }

            if (SnapshotFallbackCount > 0)
            {
                text.AppendLine(string.Format(
                    culture,
                    "{0:N0} MEP elements where STV would read the Parameter Snapshot (display units) " +
                    "because Width/Height/Diameter, Length or flow is empty",
                    SnapshotFallbackCount
                ));
            }
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
