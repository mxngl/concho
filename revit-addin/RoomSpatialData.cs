using System;
using System.Globalization;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;

namespace QTO
{
    internal class RoomAssignmentData
    {
        public string RoomId { get; init; } = "";
        public string RoomNumber { get; init; } = "";
        public string RoomName { get; init; } = "";
        public string RoomLevel { get; init; } = "";
        public string RoomAreaSquareFeet { get; init; } = "";
        public string RoomVolumeCubicFeet { get; init; } = "";
        public string RoomLocationXFeet { get; init; } = "";
        public string RoomLocationYFeet { get; init; } = "";
        public string RoomLocationZFeet { get; init; } = "";

        public static RoomAssignmentData FromElement(Document doc, Element elem)
        {
            Room? room = ResolveRoom(doc, elem);
            if (room == null)
                return new RoomAssignmentData();

            XYZ? location = (room.Location as LocationPoint)?.Point;
            return new RoomAssignmentData
            {
                RoomId = room.Id.Value.ToString(CultureInfo.InvariantCulture),
                RoomNumber = room.Number ?? "",
                RoomName = room.Name ?? "",
                RoomLevel = GetLevelName(doc, room),
                RoomAreaSquareFeet = FormatDouble(room.Area),
                RoomVolumeCubicFeet = FormatDouble(room.Volume),
                RoomLocationXFeet = FormatCoordinate(location?.X),
                RoomLocationYFeet = FormatCoordinate(location?.Y),
                RoomLocationZFeet = FormatCoordinate(location?.Z)
            };
        }

        private static Room? ResolveRoom(Document doc, Element elem)
        {
            if (elem is FamilyInstance familyInstance)
            {
                Room? familyRoom = familyInstance.Room;
                if (familyRoom != null)
                    return familyRoom;

                familyRoom = familyInstance.ToRoom ?? familyInstance.FromRoom;
                if (familyRoom != null)
                    return familyRoom;
            }

            XYZ? point = RepresentativePoint(elem);
            if (point == null)
                return null;

            try
            {
                return doc.GetRoomAtPoint(point);
            }
            catch
            {
                return null;
            }
        }

        private static XYZ? RepresentativePoint(Element elem)
        {
            if (elem.Location is LocationPoint locationPoint)
                return locationPoint.Point;

            if (elem.Location is LocationCurve locationCurve)
            {
                try
                {
                    Curve curve = locationCurve.Curve;
                    XYZ start = curve.GetEndPoint(0);
                    XYZ end = curve.GetEndPoint(1);
                    return new XYZ(
                        (start.X + end.X) / 2.0,
                        (start.Y + end.Y) / 2.0,
                        (start.Z + end.Z) / 2.0
                    );
                }
                catch
                {
                    return BoundingBoxCenter(elem);
                }
            }

            return BoundingBoxCenter(elem);
        }

        private static XYZ? BoundingBoxCenter(Element elem)
        {
            try
            {
                BoundingBoxXYZ? box = elem.get_BoundingBox(null);
                if (box == null)
                    return null;

                return new XYZ(
                    (box.Min.X + box.Max.X) / 2.0,
                    (box.Min.Y + box.Max.Y) / 2.0,
                    (box.Min.Z + box.Max.Z) / 2.0
                );
            }
            catch
            {
                return null;
            }
        }

        private static string GetLevelName(Document doc, Room room)
        {
            if (room.LevelId == ElementId.InvalidElementId)
                return "";

            Element? level = doc.GetElement(room.LevelId);
            return level?.Name ?? "";
        }

        internal static string FormatCoordinate(double? value)
        {
            return value.HasValue ? FormatDouble(value.Value) : "";
        }

        internal static string FormatDouble(double value)
        {
            return Math.Abs(value) < 1e-9
                ? ""
                : value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        internal static string EscapeCsv(string value)
        {
            value = (value ?? "").Replace("\"", "\"\"");
            if (value.Contains(",") || value.Contains("\"") || value.Contains("\n") || value.Contains("\r"))
                return $"\"{value}\"";
            return value;
        }
    }

    internal static class RoomBoundaryExporter
    {
        public static int ExportRoomsToCsv(Document doc, string filePath)
        {
            Room[] rooms = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .OfType<Room>()
                .Where(room => room.Area > 0)
                .OrderBy(room => room.Level?.Name ?? "")
                .ThenBy(room => room.Number ?? "")
                .ToArray();

            SpatialElementBoundaryOptions options = new SpatialElementBoundaryOptions
            {
                SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
            };

            StringBuilder csv = new StringBuilder();
            csv.AppendLine(
                "RoomId,RoomNumber,RoomName,Level,Area (SF),Volume (CF),Room Location X (ft),Room Location Y (ft),Room Location Z (ft),Boundary Loop,Segment Index,Start X (ft),Start Y (ft),Start Z (ft),End X (ft),End Y (ft),End Z (ft),Boundary Element Id"
            );

            foreach (Room room in rooms)
            {
                XYZ? location = (room.Location as LocationPoint)?.Point;
                IList<IList<BoundarySegment>>? boundaryLoops = null;
                try
                {
                    boundaryLoops = room.GetBoundarySegments(options);
                }
                catch
                {
                    boundaryLoops = null;
                }

                if (boundaryLoops == null || boundaryLoops.Count == 0)
                {
                    AppendRoomBoundaryRow(csv, room, location, "", "", null, "");
                    continue;
                }

                for (int loopIndex = 0; loopIndex < boundaryLoops.Count; loopIndex++)
                {
                    IList<BoundarySegment> loop = boundaryLoops[loopIndex];
                    for (int segmentIndex = 0; segmentIndex < loop.Count; segmentIndex++)
                    {
                        BoundarySegment segment = loop[segmentIndex];
                        AppendRoomBoundaryRow(
                            csv,
                            room,
                            location,
                            (loopIndex + 1).ToString(CultureInfo.InvariantCulture),
                            (segmentIndex + 1).ToString(CultureInfo.InvariantCulture),
                            segment.GetCurve(),
                            segment.ElementId == ElementId.InvalidElementId
                                ? ""
                                : segment.ElementId.Value.ToString(CultureInfo.InvariantCulture)
                        );
                    }
                }
            }

            File.WriteAllText(filePath, csv.ToString(), Encoding.UTF8);
            return rooms.Length;
        }

        private static void AppendRoomBoundaryRow(
            StringBuilder csv,
            Room room,
            XYZ? location,
            string loopIndex,
            string segmentIndex,
            Curve? curve,
            string boundaryElementId)
        {
            XYZ? start = null;
            XYZ? end = null;
            if (curve != null)
            {
                start = curve.GetEndPoint(0);
                end = curve.GetEndPoint(1);
            }

            csv.AppendLine(string.Join(",",
                RoomAssignmentData.EscapeCsv(room.Id.Value.ToString(CultureInfo.InvariantCulture)),
                RoomAssignmentData.EscapeCsv(room.Number ?? ""),
                RoomAssignmentData.EscapeCsv(room.Name ?? ""),
                RoomAssignmentData.EscapeCsv(room.Level?.Name ?? ""),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatDouble(room.Area)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatDouble(room.Volume)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(location?.X)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(location?.Y)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(location?.Z)),
                RoomAssignmentData.EscapeCsv(loopIndex),
                RoomAssignmentData.EscapeCsv(segmentIndex),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(start?.X)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(start?.Y)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(start?.Z)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(end?.X)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(end?.Y)),
                RoomAssignmentData.EscapeCsv(RoomAssignmentData.FormatCoordinate(end?.Z)),
                RoomAssignmentData.EscapeCsv(boundaryElementId)
            ));
        }
    }
}
