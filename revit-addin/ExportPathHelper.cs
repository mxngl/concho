using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using Autodesk.Revit.DB;

namespace QTO
{
    /// <summary>
    /// Resolves the export folder from <c>concho_addin.json</c> next to <c>QTO.dll</c>.
    /// If the file is missing, has no folder or the folder doesn't exist, the user picks a folder
    /// in a dialog and the choice is saved to that file. A relative <c>export_folder</c> is resolved
    /// against the DLL's folder.
    /// </summary>
    internal static class ExportPathHelper
    {
        public const string ConfigFileName = "concho_addin.json";

        /// <summary>
        /// Returns the export folder, or null if the user cancelled the folder dialog.
        /// </summary>
        public static string? GetExportFolder()
        {
            string configPath = GetConfigPath();
            AddinConfig config = LoadConfig(configPath);

            string? folder = ResolveFolder(config.ExportFolder);
            if (folder != null && Directory.Exists(folder))
                return folder;

            string? chosen = AskForFolder(folder);
            if (chosen == null)
                return null;

            config.ExportFolder = chosen;
            try
            {
                SaveConfig(configPath, config);
            }
            catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
            {
                Autodesk.Revit.UI.TaskDialog.Show(
                    "Concho export folder",
                    $"Could not save the folder to:\n{configPath}\n\n{ex.Message}\n\n" +
                    "The export continues, but you will be asked again next time."
                );
            }

            return chosen;
        }

        public static string GetScheduleFilePath(Document doc, string exportFolder, string exportSuffix)
        {
            string modelBaseName = GetModelBaseName(doc);
            return Path.Combine(exportFolder, $"{modelBaseName}_{exportSuffix}.csv");
        }

        public static string GetConfigPath()
        {
            string assemblyDirectory = Path.GetDirectoryName(
                System.Reflection.Assembly.GetExecutingAssembly().Location
            ) ?? "";

            return Path.Combine(assemblyDirectory, ConfigFileName);
        }

        private static string? ResolveFolder(string? configured)
        {
            if (string.IsNullOrWhiteSpace(configured))
                return null;

            string expanded = Environment.ExpandEnvironmentVariables(configured.Trim());
            string baseDirectory = Path.GetDirectoryName(GetConfigPath()) ?? "";
            return Path.GetFullPath(Path.IsPathRooted(expanded)
                ? expanded
                : Path.Combine(baseDirectory, expanded));
        }

        private static string? AskForFolder(string? initialFolder)
        {
            Microsoft.Win32.OpenFolderDialog dialog = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "Concho: choose the folder for the CSV exports (saved to " + ConfigFileName + ")",
                Multiselect = false
            };

            if (initialFolder != null)
            {
                string? existingParent = initialFolder;
                while (existingParent != null && !Directory.Exists(existingParent))
                    existingParent = Path.GetDirectoryName(existingParent);

                if (existingParent != null)
                    dialog.InitialDirectory = existingParent;
            }

            return dialog.ShowDialog() == true ? dialog.FolderName : null;
        }

        private static AddinConfig LoadConfig(string configPath)
        {
            if (!File.Exists(configPath))
                return new AddinConfig();

            try
            {
                return JsonSerializer.Deserialize<AddinConfig>(File.ReadAllText(configPath)) ?? new AddinConfig();
            }
            catch (JsonException)
            {
                // Unreadable file: ask again and overwrite it with the new choice.
                return new AddinConfig();
            }
        }

        private static void SaveConfig(string configPath, AddinConfig config)
        {
            JsonSerializerOptions options = new JsonSerializerOptions { WriteIndented = true };
            File.WriteAllText(configPath, JsonSerializer.Serialize(config, options));
        }

        private static string GetModelBaseName(Document doc)
        {
            string rawName = !string.IsNullOrWhiteSpace(doc.PathName)
                ? Path.GetFileNameWithoutExtension(doc.PathName)
                : doc.Title;

            if (string.IsNullOrWhiteSpace(rawName))
            {
                rawName = "Untitled_Model";
            }

            char[] invalidChars = Path.GetInvalidFileNameChars();
            string sanitized = new string(
                rawName
                    .Select(ch => invalidChars.Contains(ch) ? '_' : ch)
                    .ToArray()
            ).Trim();

            return string.IsNullOrWhiteSpace(sanitized) ? "Untitled_Model" : sanitized;
        }

        private sealed class AddinConfig
        {
            [JsonPropertyName("export_folder")]
            public string? ExportFolder { get; set; }
        }
    }
}
