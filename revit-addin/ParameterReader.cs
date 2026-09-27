using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace QTO
{
    /// <summary>
    /// One lookup candidate: built-in parameters (language-independent) first, then the English
    /// parameter name as fallback. Each is tried on the instance, then on its type.
    /// </summary>
    internal sealed class ParamCandidate
    {
        public ParamCandidate(string name, params BuiltInParameter[] builtIns)
        {
            Name = name;
            BuiltIns = builtIns;
        }

        public string Name { get; }
        public BuiltInParameter[] BuiltIns { get; }

        public static implicit operator ParamCandidate(string name) => new ParamCandidate(name);
    }

    /// <summary>
    /// Unit-safe, language-independent parameter reading for the CSV exports (P4.5).
    /// Numbers are converted from Revit's internal units into fixed export units and written as
    /// plain invariant decimals, so the CSV does not depend on the project's display units.
    /// </summary>
    internal static class ParameterReader
    {
        public static readonly ForgeTypeId[] Feet = { UnitTypeId.Feet };
        public static readonly ForgeTypeId[] Inches = { UnitTypeId.Inches };
        public static readonly ForgeTypeId[] SquareFeet = { UnitTypeId.SquareFeet };
        public static readonly ForgeTypeId[] CubicFeet = { UnitTypeId.CubicFeet };
        public static readonly ForgeTypeId[] CubicMetersPerSecond = { UnitTypeId.CubicMetersPerSecond };
        public static readonly ForgeTypeId[] Pascals = { UnitTypeId.Pascals };
        public static readonly ForgeTypeId[] Watts = { UnitTypeId.Watts };
        public static readonly ForgeTypeId[] Volts = { UnitTypeId.Volts };
        public static readonly ForgeTypeId[] Amperes = { UnitTypeId.Amperes };
        public static readonly ForgeTypeId[] VoltAmperes = { UnitTypeId.VoltAmperes };

        /// <summary>Mass in kg; a force-type weight in kgf (numerically the same for the engines).</summary>
        public static readonly ForgeTypeId[] Kilograms = { UnitTypeId.Kilograms, UnitTypeId.KilogramsForce };

        /// <summary>Per length in kg/m or kgf/m; per volume (unit weight, density) in kN/m³ or kg/m³.</summary>
        public static readonly ForgeTypeId[] UnitWeight =
        {
            UnitTypeId.KilogramsPerMeter,
            UnitTypeId.KilogramsForcePerMeter,
            UnitTypeId.KilonewtonsPerCubicMeter,
            UnitTypeId.KilogramsPerCubicMeter
        };

        private static readonly HashSet<string> ImperialLengthUnits = new HashSet<string>
        {
            UnitTypeId.Feet.TypeId,
            UnitTypeId.Inches.TypeId,
            UnitTypeId.FeetFractionalInches.TypeId,
            UnitTypeId.FractionalInches.TypeId,
            UnitTypeId.UsSurveyFeet.TypeId
        };

        /// <summary>
        /// First Double parameter among the candidates whose spec can be expressed in one of the
        /// target units, converted from internal units. Null if none has a value.
        /// </summary>
        public static double? Number(Document doc, Element elem, ForgeTypeId[] units, params ParamCandidate[] candidates)
        {
            Element? typeElem = GetType(doc, elem);
            foreach (ParamCandidate candidate in candidates)
            {
                foreach (Parameter? parameter in Lookups(elem, typeElem, candidate))
                {
                    double? value = Convert(parameter, units);
                    if (value.HasValue)
                        return value;
                }
            }

            return null;
        }

        /// <summary>First non-empty text value (String, Integer or ElementId parameter) among the candidates.</summary>
        public static string Text(Document doc, Element elem, params ParamCandidate[] candidates)
        {
            Element? typeElem = GetType(doc, elem);
            foreach (ParamCandidate candidate in candidates)
            {
                foreach (Parameter? parameter in Lookups(elem, typeElem, candidate))
                {
                    string value = TextValue(parameter, doc);
                    if (!string.IsNullOrWhiteSpace(value))
                        return value;
                }
            }

            return "";
        }

        /// <summary>Assembly Code: built-in parameter (instance, then type), English name as fallback.</summary>
        public static string AssemblyCode(Document doc, Element elem)
        {
            return Text(doc, elem, new ParamCandidate(
                "Assembly Code",
#if REVIT2025
                BuiltInParameter.UNIFORMAT_CODE
#else
                BuiltInParameter.ASSEMBLY_CODE
#endif
            ));
        }

        public static string AssemblyDescription(Document doc, Element elem)
        {
            return Text(doc, elem, new ParamCandidate(
                "Assembly Description",
#if REVIT2025
                BuiltInParameter.UNIFORMAT_DESCRIPTION
#else
                BuiltInParameter.ASSEMBLY_DESCRIPTION
#endif
            ));
        }

        /// <summary>Plain invariant decimal (no unit, no thousands separator); empty for null.</summary>
        public static string Format(double? value)
        {
            if (!value.HasValue || double.IsNaN(value.Value) || double.IsInfinity(value.Value))
                return "";

            string text = value.Value.ToString("0.######", CultureInfo.InvariantCulture);
            return text == "-0" ? "0" : text;
        }

        /// <summary>
        /// Fixed feet-inch text for decimal feet, e.g. 12.53125 → <c>12' - 6.375"</c> (inches with
        /// 3 decimals, no fractions, invariant culture). Only used for the MEP Length column, which
        /// the STV MEP importer reads with a feet/inch parser. Empty for null.
        /// </summary>
        public static string FormatFeetInches(double? feet)
        {
            if (!feet.HasValue || double.IsNaN(feet.Value) || double.IsInfinity(feet.Value))
                return "";

            double totalInches = Math.Round(Math.Abs(feet.Value) * 12.0, 3, MidpointRounding.AwayFromZero);
            long wholeFeet = (long)Math.Floor(totalInches / 12.0);
            double inches = Math.Round(totalInches - wholeFeet * 12.0, 3, MidpointRounding.AwayFromZero);
            if (inches >= 12.0)
            {
                wholeFeet += 1;
                inches = 0.0;
            }

            string sign = feet.Value < 0 && (wholeFeet > 0 || inches > 0) ? "-" : "";
            return string.Format(CultureInfo.InvariantCulture, "{0}{1}' - {2:0.000}\"", sign, wholeFeet, inches);
        }

        /// <summary>Inches with up to 3 decimals and an inch mark, e.g. <c>4"</c>, <c>12.5"</c>.</summary>
        public static string FormatInchMark(double inches)
        {
            return inches.ToString("0.###", CultureInfo.InvariantCulture) + "\"";
        }

        /// <summary>True if the project displays this spec (e.g. Length, DuctSize) in non-imperial units.</summary>
        public static bool IsMetric(Document doc, ForgeTypeId spec)
        {
            try
            {
                ForgeTypeId unit = doc.GetUnits().GetFormatOptions(spec).GetUnitTypeId();
                return !ImperialLengthUnits.Contains(unit.TypeId);
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static IEnumerable<Parameter?> Lookups(Element elem, Element? typeElem, ParamCandidate candidate)
        {
            foreach (BuiltInParameter builtIn in candidate.BuiltIns)
            {
                yield return elem.get_Parameter(builtIn);
                if (typeElem != null)
                    yield return typeElem.get_Parameter(builtIn);
            }

            yield return elem.LookupParameter(candidate.Name);
            if (typeElem != null)
                yield return typeElem.LookupParameter(candidate.Name);
        }

        private static Element? GetType(Document doc, Element elem)
        {
            ElementId typeId = elem.GetTypeId();
            return typeId == ElementId.InvalidElementId ? null : doc.GetElement(typeId);
        }

        private static double? Convert(Parameter? parameter, ForgeTypeId[] units)
        {
            if (parameter == null || parameter.StorageType != StorageType.Double || !parameter.HasValue)
                return null;

            try
            {
                ForgeTypeId spec = parameter.Definition.GetDataType();
                ForgeTypeId? unit = units.FirstOrDefault(u => UnitUtils.IsValidUnit(spec, u));
                if (unit == null)
                    return null;

                return UnitUtils.ConvertFromInternalUnits(parameter.AsDouble(), unit);
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static string TextValue(Parameter? parameter, Document doc)
        {
            if (parameter == null || !parameter.HasValue)
                return "";

            try
            {
                switch (parameter.StorageType)
                {
                    case StorageType.String:
                        return parameter.AsString() ?? "";

                    case StorageType.Integer:
                        return parameter.AsInteger().ToString(CultureInfo.InvariantCulture);

                    case StorageType.ElementId:
                        ElementId id = parameter.AsElementId();
                        if (id == ElementId.InvalidElementId)
                            return "";
                        return doc.GetElement(id)?.Name ?? id.Value.ToString(CultureInfo.InvariantCulture);

                    default:
                        return "";
                }
            }
            catch (Exception)
            {
                return "";
            }
        }
    }
}
