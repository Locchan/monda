import datetime
import logging
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger: logging.Logger = get_logger()


class HikEvent:
    NS: dict[str, str] = {"h": "http://www.hikvision.com/ver20/XMLSchema"}

    def __init__(self, name: str, state: str, date: str, source: str) -> None:
        config = read_config()
        self.name = name
        self.state = state
        self.source = source
        timezone = config.get("TZ", "UTC")
        dt = datetime.datetime.fromisoformat(date)
        tz = ZoneInfo(timezone)
        self.date = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
        logger.debug(repr(self))

    def __repr__(self) -> str:
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

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "state": self.state,
            "date": self.date.isoformat(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HikEvent":
        return cls(name=d["name"], state=d["state"], date=d["date"], source=d["source"])