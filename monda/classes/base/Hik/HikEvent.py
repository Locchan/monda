import datetime
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from monda.utils.logger import get_logger
from monda.utils.misc import read_config

config = read_config()
logger = get_logger()
if "TZ" in config:
    timezone = config["TZ"]
else:
    timezone = "UTC"

logger.info(f"Using timezone: {timezone}")


class HikEvent:
    NS = {"h": "http://www.hikvision.com/ver20/XMLSchema"}

    def __init__(self, name, state, date, source):
        self.name = name
        self.state = state
        self.source = source
        dt = datetime.datetime.fromisoformat(date)
        tz = ZoneInfo(timezone)
        self.date = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
        logger.debug(repr(self))

    def __repr__(self):
        return f"HikEvent(source={self.source!r}, name={self.name!r}, state={self.state!r}, date={self.date.isoformat()})"

    @classmethod
    def from_xml(cls, xml_str: str, source: str) -> "HikEvent":
        root = ET.fromstring(xml_str)
        return cls(
            name=root.find("h:eventType", cls.NS).text,
            state=root.find("h:eventState", cls.NS).text,
            date=root.find("h:dateTime", cls.NS).text,
            source=source,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "date": self.date.isoformat(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HikEvent":
        return cls(name=d["name"], state=d["state"], date=d["date"], source=d["source"])