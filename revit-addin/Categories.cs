using System.Collections.Generic;
using Autodesk.Revit.DB;

namespace QTO
{
    /// <summary>
    /// English category names independent of the Revit UI language (P4.5). The STV mapping table
    /// and TVD key on the English names; the Revit API has no English label for categories in a
    /// localized Revit, so the names are a fixed table for every category the add-in exports.
    /// Names marked "verified" appear in English Revit exports of the Island reference models or
    /// in the STV mapping tables; the others follow the English Revit UI and are checked in the
    /// Revit test (in English Revit, "Category" and "Category (local)" must be identical).
    /// </summary>
    internal static class Categories
    {
        private static readonly Dictionary<BuiltInCategory, string> EnglishNames =
            new Dictionary<BuiltInCategory, string>
            {
                // Architecture (verified)
                { BuiltInCategory.OST_Walls, "Walls" },
                { BuiltInCategory.OST_Doors, "Doors" },
                { BuiltInCategory.OST_Windows, "Windows" },
                { BuiltInCategory.OST_Floors, "Floors" },
                { BuiltInCategory.OST_Roofs, "Roofs" },
                { BuiltInCategory.OST_Ceilings, "Ceilings" },
                { BuiltInCategory.OST_Parts, "Parts" },
                { BuiltInCategory.OST_CurtainWallPanels, "Curtain Panels" },
                { BuiltInCategory.OST_CurtainWallMullions, "Curtain Wall Mullions" },
                { BuiltInCategory.OST_Stairs, "Stairs" },
                { BuiltInCategory.OST_StairsRuns, "Runs" },
                { BuiltInCategory.OST_StairsLandings, "Landings" },
                { BuiltInCategory.OST_GenericModel, "Generic Models" },
                { BuiltInCategory.OST_Casework, "Casework" },
                { BuiltInCategory.OST_Furniture, "Furniture" },
                { BuiltInCategory.OST_FurnitureSystems, "Furniture Systems" },
                { BuiltInCategory.OST_PlumbingFixtures, "Plumbing Fixtures" },
                // Architecture (English UI, not in the reference exports)
                { BuiltInCategory.OST_Railings, "Railings" },
                { BuiltInCategory.OST_StairsRailing, "Railings" },

                // Structural (verified)
                { BuiltInCategory.OST_StructuralColumns, "Structural Columns" },
                { BuiltInCategory.OST_StructuralFraming, "Structural Framing" },
                { BuiltInCategory.OST_StructuralFoundation, "Structural Foundations" },
                // Structural (English UI, not in the reference exports)
                { BuiltInCategory.OST_StructuralStiffener, "Structural Stiffeners" },
                { BuiltInCategory.OST_StructuralTruss, "Structural Trusses" },
                { BuiltInCategory.OST_StructConnections, "Structural Connections" },
                { BuiltInCategory.OST_StructConnectionPlates, "Structural Connection Plates" },
                { BuiltInCategory.OST_StructConnectionBolts, "Structural Connection Bolts" },
                { BuiltInCategory.OST_StructConnectionAnchors, "Structural Connection Anchors" },
                { BuiltInCategory.OST_Rebar, "Structural Rebar" },
                { BuiltInCategory.OST_AreaRein, "Structural Area Reinforcement" },
                { BuiltInCategory.OST_PathRein, "Structural Path Reinforcement" },
                { BuiltInCategory.OST_FabricReinforcement, "Structural Fabric Reinforcement" },

                // MEP (verified)
                { BuiltInCategory.OST_DuctCurves, "Ducts" },
                { BuiltInCategory.OST_DuctFitting, "Duct Fittings" },
                { BuiltInCategory.OST_DuctTerminal, "Air Terminals" },
                { BuiltInCategory.OST_FlexDuctCurves, "Flex Ducts" },
                { BuiltInCategory.OST_PipeCurves, "Pipes" },
                { BuiltInCategory.OST_PipeFitting, "Pipe Fittings" },
                { BuiltInCategory.OST_PipeAccessory, "Pipe Accessories" },
                { BuiltInCategory.OST_FlexPipeCurves, "Flex Pipes" },
                { BuiltInCategory.OST_MechanicalEquipment, "Mechanical Equipment" },
                { BuiltInCategory.OST_ElectricalEquipment, "Electrical Equipment" },
                { BuiltInCategory.OST_ElectricalFixtures, "Electrical Fixtures" },
                // MEP (English UI, not in the reference exports)
                { BuiltInCategory.OST_DuctAccessory, "Duct Accessories" },
                { BuiltInCategory.OST_CableTray, "Cable Trays" },
                { BuiltInCategory.OST_CableTrayFitting, "Cable Tray Fittings" },
                { BuiltInCategory.OST_Conduit, "Conduits" },
                { BuiltInCategory.OST_ConduitFitting, "Conduit Fittings" },
                { BuiltInCategory.OST_LightingFixtures, "Lighting Fixtures" },
                { BuiltInCategory.OST_Sprinklers, "Sprinklers" },
            };

        /// <summary>English name of the category; the Revit (possibly localized) name if not in the table.</summary>
        public static string English(Category? category)
        {
            if (category == null)
                return "";

            BuiltInCategory? builtIn = BuiltIn(category);
            if (builtIn.HasValue && EnglishNames.TryGetValue(builtIn.Value, out string? name))
                return name;

            return category.Name ?? "";
        }

        /// <summary>The category name as Revit shows it (UI language).</summary>
        public static string Local(Category? category)
        {
            return category?.Name ?? "";
        }

        public static BuiltInCategory? BuiltIn(Category? category)
        {
            if (category == null)
                return null;

            long id = category.Id.Value;
            if (id >= 0 || id < int.MinValue)
                return null;

            return (BuiltInCategory)(int)id;
        }

        public static bool Is(Element? elem, BuiltInCategory builtIn)
        {
            return BuiltIn(elem?.Category) == builtIn;
        }
    }

    /// <summary>
    /// Source element of a Revit part (P4.5): the element the part was divided from, following
    /// part-of-part chains. Null if the source is in a linked model or can't be resolved.
    /// </summary>
    internal static class PartSource
    {
        public static Element? SourceElement(Document doc, Element elem)
        {
            Element? current = elem;
            for (int depth = 0; depth < 10 && current is Part part; depth++)
            {
                Element? next = null;
                foreach (LinkElementId linkId in part.GetSourceElementIds())
                {
                    if (linkId.LinkInstanceId != ElementId.InvalidElementId)
                        continue;

                    next = doc.GetElement(linkId.HostElementId);
                    if (next != null)
                        break;
                }

                if (next == null)
                    return null;

                current = next;
            }

            return current is Part ? null : current;
        }
    }
}
