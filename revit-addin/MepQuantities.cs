using Autodesk.Revit.DB;

namespace QTO
{
    /// <summary>
    /// Numeric columns of the MEP export (P4.5), converted from Revit's internal units into the
    /// units the STV MEP importer expects: dimensions and thicknesses in inches, length in feet,
    /// area SF, volume CF, weight kg, air/water flow m³/s (see docs/model-requirements.md).
    /// </summary>
    internal sealed class MepQuantities
    {
        public double? DiameterInches { get; private set; }
        public double? WidthInches { get; private set; }
        public double? HeightInches { get; private set; }
        public double? LengthFeet { get; private set; }
        public double? Area { get; private set; }
        public double? Volume { get; private set; }
        public double? Weight { get; private set; }
        public double? UnitWeight { get; private set; }
        public double? InsulationThicknessInches { get; private set; }
        public double? LiningThicknessInches { get; private set; }
        public double? Airflow { get; private set; }
        public double? Flow { get; private set; }
        public double? PressureDrop { get; private set; }
        public double? CoolingCapacity { get; private set; }
        public double? HeatingCapacity { get; private set; }
        public double? Power { get; private set; }
        public double? Voltage { get; private set; }
        public double? Current { get; private set; }
        public double? ApparentLoad { get; private set; }
        public double? ConnectedLoad { get; private set; }

        public static MepQuantities Read(Document doc, Element elem)
        {
            ParamCandidate flowCandidate = new ParamCandidate(
                "Flow",
                BuiltInParameter.RBS_DUCT_FLOW_PARAM,
                BuiltInParameter.RBS_PIPE_FLOW_PARAM
            );

            return new MepQuantities
            {
                DiameterInches = ParameterReader.Number(doc, elem, ParameterReader.Inches,
                    new ParamCandidate(
                        "Diameter",
                        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
                        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
                        BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
                    ),
                    "Nominal Diameter",
                    "Duct Diameter"),
                WidthInches = ParameterReader.Number(doc, elem, ParameterReader.Inches,
                    new ParamCandidate(
                        "Width",
                        BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
                        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
                    ),
                    "Nominal Width",
                    "Duct Width"),
                HeightInches = ParameterReader.Number(doc, elem, ParameterReader.Inches,
                    new ParamCandidate(
                        "Height",
                        BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
                        BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM
                    ),
                    "Nominal Height",
                    "Duct Height"),
                // Same fallbacks STV would otherwise read from the Parameter Snapshot.
                LengthFeet = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                    new ParamCandidate("Length", BuiltInParameter.CURVE_ELEM_LENGTH),
                    "Duct Length",
                    "Computed Length",
                    "Length 1",
                    "Duct Length 1"),
                Area = ParameterReader.Number(doc, elem, ParameterReader.SquareFeet,
                    new ParamCandidate(
                        "Area",
                        BuiltInParameter.RBS_CURVE_SURFACE_AREA,
                        BuiltInParameter.HOST_AREA_COMPUTED
                    ),
                    "Surface Area"),
                Volume = ParameterReader.Number(doc, elem, ParameterReader.CubicFeet,
                    new ParamCandidate("Volume", BuiltInParameter.HOST_VOLUME_COMPUTED)),
                Weight = ParameterReader.Number(doc, elem, ParameterReader.Kilograms,
                    "Weight",
                    "Calculated Weight",
                    "Mass"),
                UnitWeight = ParameterReader.Number(doc, elem, ParameterReader.UnitWeight,
                    "Unit Weight",
                    "Weight per Unit Length",
                    "Mass per Unit Length"),
                InsulationThicknessInches = ParameterReader.Number(doc, elem, ParameterReader.Inches,
                    new ParamCandidate("Insulation Thickness", BuiltInParameter.RBS_REFERENCE_INSULATION_THICKNESS)),
                LiningThicknessInches = ParameterReader.Number(doc, elem, ParameterReader.Inches,
                    new ParamCandidate("Lining Thickness", BuiltInParameter.RBS_REFERENCE_LINING_THICKNESS)),
                Airflow = ParameterReader.Number(doc, elem, ParameterReader.CubicMetersPerSecond,
                    "Air Flow",
                    "Airflow",
                    "Calculated Supply Air Flow",
                    "Calculated Exhaust Air Flow",
                    "Calculated Return Air Flow",
                    flowCandidate,
                    "Supply Air Outlet Flow",
                    "Supply Air Inlet Flow",
                    "Return Air Inlet Flow"),
                Flow = ParameterReader.Number(doc, elem, ParameterReader.CubicMetersPerSecond,
                    flowCandidate,
                    "Flow Rate",
                    "Actual Flow",
                    "Demand Flow"),
                PressureDrop = ParameterReader.Number(doc, elem, ParameterReader.Pascals,
                    new ParamCandidate(
                        "Pressure Drop",
                        BuiltInParameter.RBS_DUCT_PRESSURE_DROP,
                        BuiltInParameter.RBS_PIPE_PRESSUREDROP_PARAM
                    ),
                    "Calculated Pressure Drop",
                    "Fitting Pressure Drop"),
                CoolingCapacity = ParameterReader.Number(doc, elem, ParameterReader.Watts,
                    "Cooling Capacity",
                    "Total Cooling Capacity",
                    "Sensible Cooling Capacity"),
                HeatingCapacity = ParameterReader.Number(doc, elem, ParameterReader.Watts,
                    "Heating Capacity",
                    "Heating Load",
                    "Total Heating Capacity"),
                Power = ParameterReader.Number(doc, elem, ParameterReader.Watts,
                    "Power",
                    "Motor Power",
                    "Input Power"),
                Voltage = ParameterReader.Number(doc, elem, ParameterReader.Volts, "Voltage"),
                Current = ParameterReader.Number(doc, elem, ParameterReader.Amperes,
                    "Current",
                    "Current Rating"),
                ApparentLoad = ParameterReader.Number(doc, elem, ParameterReader.VoltAmperes, "Apparent Load"),
                ConnectedLoad = ParameterReader.Number(doc, elem, ParameterReader.VoltAmperes, "Connected Load")
            };
        }
    }
}
