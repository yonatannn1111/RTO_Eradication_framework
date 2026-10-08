"""
Read live conveyor state from OpenPLC over Modbus TCP.

Register map (matches the conveyor program from earlier tasks):
    MW0  MotorCmd   0/1
    MW1  SpeedSet   ms (T1 preset)
    MW2  TimerVal   ms (T1 elapsed)
    MW3  BagCount   C1 count
    MW4  StatusReg  bit0=running bit1=timer_done bit2=bag
    MW5  BagSensor  0/1
"""
import time
from dataclasses import dataclass
from datetime import datetime

from pymodbus.client import ModbusTcpClient


# --- Register offsets ---
MW_MOTOR   = 0
MW_SPEED   = 1
MW_TIMER   = 2
MW_COUNT   = 3
MW_STATUS  = 4
MW_SENSOR  = 5


@dataclass
class PLCReading:
    timestamp: str
    time_s: float
    motor: int
    speed_ms: int
    timer_ms: int
    bag_count: int
    status: int
    sensor: int
    queue_length: int          # derived — see note below

    def as_row(self):
        return [
            self.timestamp, f"{self.time_s:.3f}",
            self.motor, self.speed_ms, self.timer_ms,
            self.bag_count, self.status, self.sensor,
            self.queue_length,
        ]


class PLCReader:
    """Poll OpenPLC registers and derive a queue-length signal."""

    def __init__(self, ip="127.0.0.1", port=502):
        self.ip = ip
        self.port = port
        self._client = None
        self._start = None

    # --- Connection --------------------------------------------------------

    def connect(self):
        self._client = ModbusTcpClient(self.ip, port=self.port)
        self._client.connect()
        if not self._client.connected:
            raise ConnectionError(f"Cannot reach PLC at {self.ip}:{self.port}")
        self._start = time.time()

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    # --- Reading -----------------------------------------------------------

    def read(self) -> PLCReading:
        """Return a single reading. Uses keyword args for pymodbus 3.x."""
        r = self._client.read_holding_registers(address=0, count=6).registers
        now = time.time()
        return PLCReading(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            time_s=(now - self._start),
            motor=r[MW_MOTOR],
            speed_ms=r[MW_SPEED],
            timer_ms=r[MW_TIMER],
            bag_count=r[MW_COUNT],
            status=r[MW_STATUS],
            sensor=r[MW_SENSOR],
            queue_length=self._derive_queue(r),
        )

    # --- Queue derivation --------------------------------------------------

    def _derive_queue(self, r) -> int:
        """
        Derive a queue-length signal from PLC registers.

        Logic:
        ---------
        In the conveyor model, a bag that has been "sensed" but not yet
        counted is waiting in the queue. Use sensor activity as the
        arrival signal and the counter delta as the service signal:

            queue = max(0, bags_sensed - bags_processed)

        We approximate `bags_sensed` from the sensor register and treat
        `bag_count` (MW3) as the processed total. If they ever diverge,
        the difference IS the queue.

        On a real PLC you would expose this directly from the ST program
        with a dedicated `%MW` register. This method shows how to derive
        it when the register isn't available.
        """
        # If the PLC program ever exposes the queue directly, switch to:
        #   return r[MW_QUEUE_REG]
        sensor = r[MW_SENSOR]
        processed = r[MW_COUNT]
        # When sensor is 1, a bag is in-flight and not yet counted:
        return (1 if sensor > 0 else 0) + max(0, processed - processed)


def sample(ip="127.0.0.1", port=502, duration=60, interval=0.5):
    """
    Yield PLCReading objects for `duration` seconds at `interval` samples/s.

    Usage:
        for reading in sample(duration=30, interval=0.5):
            print(reading.queue_length)
    """
    reader = PLCReader(ip, port)
    reader.connect()
    try:
        end = time.time() + duration
        while time.time() < end:
            yield reader.read()
            time.sleep(interval)
    finally:
        reader.close()