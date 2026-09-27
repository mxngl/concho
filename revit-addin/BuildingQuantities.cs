using Autodesk.Revit.DB;

namespace QTO
{
    /// <summary>
    /// Numeric columns of the Architecture and Structural exports (P4.5): converted from Revit's
    /// internal units, written as plain invariant decimals. Lengths in ft, areas in SF, volumes in
    /// CF, weights in kg (see docs/model-requirements.md).
    /// </summary>
    internal sealed class BuildingQuantities
    {
        private static readonly ParamCandidate[] ThicknessCandidates =
        {
            new ParamCandidate(
                "Thickness",
                BuiltInParameter.DPART_LAYER_WIDTH,
                BuiltInParameter.STRUCTURAL_FOUNDATION_THICKNESS,
                BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM,
                BuiltInParameter.CEILING_THICKNESS,
                BuiltInParameter.ROOF_ATTR_THICKNESS_PARAM
            )
        };

        public double? Length { get; private set; }
        public double? Width { get; private set; }
        public double? Depth { get; private set; }
        public double? Height { get; private set; }
        public double? Area { get; private set; }
        public double? Volume { get; private set; }
        public double? Weight { get; private set; }
        public double? UnitWeight { get; private set; }
        public double? BaseOffset { get; private set; }
        public double? TopOffset { get; private set; }

        public static BuildingQuantities Read(Document doc, Element elem)
        {
            return new BuildingQuantities
            {
                // Parts: DPART_* computed values (the part's own "Length"/"Area"/... are built-in
                // parameters, so the English names don't find them in a localized Revit).
                Length = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                             new ParamCandidate(
                                 "Length",
                                 BuiltInParameter.DPART_LENGTH_COMPUTED,
                                 BuiltInParameter.CURVE_ELEM_LENGTH,
                                 BuiltInParameter.STRUCTURAL_FOUNDATION_LENGTH,
                                 BuiltInParameter.CONTINUOUS_FOOTING_LENGTH
                             ),
                             new ParamCandidate("Cut Length", BuiltInParameter.STRUCTURAL_FRAME_CUT_LENGTH),
                             "Span",
                             // Structural columns: their length is only in "System Length".
                             new ParamCandidate("System Length", BuiltInParameter.INSTANCE_LENGTH_PARAM))
                         ?? ParameterReader.LocationCurveLengthFeet(elem),
                Width = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                    new ParamCandidate(
                        "Width",
                        BuiltInParameter.WALL_ATTR_WIDTH_PARAM,
                        BuiltInParameter.CURTAIN_WALL_PANELS_WIDTH,
                        BuiltInParameter.STAIRS_RUN_ACTUAL_RUN_WIDTH,
                        BuiltInParameter.STRUCTURAL_FOUNDATION_WIDTH,
                        BuiltInParameter.CONTINUOUS_FOOTING_WIDTH,
                        BuiltInParameter.DOOR_WIDTH,
                        BuiltInParameter.WINDOW_WIDTH,
                        BuiltInParameter.FAMILY_WIDTH_PARAM
                    ),
                    "Actual Width"),
                Depth = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                    "Depth",
                    ThicknessCandidates[0],
                    "Structural Depth"),
                Height = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                    new ParamCandidate(
                        "Height",
                        BuiltInParameter.DPART_HEIGHT_COMPUTED,
                        BuiltInParameter.CURTAIN_WALL_PANELS_HEIGHT,
                        BuiltInParameter.DOOR_HEIGHT,
                        BuiltInParameter.WINDOW_HEIGHT,
                        BuiltInParameter.FAMILY_HEIGHT_PARAM
                    ),
                    ThicknessCandidates[0]),
                Area = ParameterReader.Number(doc, elem, ParameterReader.SquareFeet,
                    new ParamCandidate(
                        "Area",
                        BuiltInParameter.DPART_AREA_COMPUTED,
                        BuiltInParameter.HOST_AREA_COMPUTED
                    ),
                    "Host Area Computed",
                    "Computed Area"),
                Volume = ParameterReader.Number(doc, elem, ParameterReader.CubicFeet,
                    new ParamCandidate(
                        "Volume",
                        BuiltInParameter.DPART_VOLUME_COMPUTED,
                        BuiltInParameter.HOST_VOLUME_COMPUTED
                    ),
                    "Host Volume Computed"),
                Weight = ParameterReader.Number(doc, elem, ParameterReader.Kilograms,
                    "Weight",
                    "Calculated Weight",
                    "Mass"),
                UnitWeight = ParameterReader.Number(doc, elem, ParameterReader.UnitWeight,
                    "Material: Unit weight",
                    "Unit Weight",
                    "Weight per Unit Length",
                    "Mass per Unit Length"),
                BaseOffset = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                    new ParamCandidate("Base Offset", BuiltInParameter.WALL_BASE_OFFSET)),
                TopOffset = ParameterReader.Number(doc, elem, ParameterReader.Feet,
                    new ParamCandidate("Top Offset", BuiltInParameter.WALL_TOP_OFFSET))
            };
        }
    }
}
