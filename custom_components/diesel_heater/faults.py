"""APK-backed fault presentation; raw fault values remain in coordinator data."""

from .const import ABBA_ERROR_NAMES, ERROR_NAMES, HEATGENIE_ERROR_NAMES, WARM_DRIVE_ERROR_NAMES

# Sunster 2.2.000 English localization. Family identity is carried on the wire.
SUNSTER_ERROR_NAMES = {
    "TY": {
        1: "E-01: Startup failed",
        2: "E-02: Out of fuel, shutdown",
        3: "E-03: Voltage anomaly",
        4: "E-04: Exhaust sensor anomaly",
        5: "E-05: Intake sensor anomaly",
        6: "E-06: Oil pump anomaly",
        7: "E-07: Fan anomaly",
        8: "E-08: Ignition plug anomaly",
        9: "E-09: Overheat protection",
        10: "E-10: Heater temperature sensor anomaly",
        11: "E-11: CO Over limit",
        50: "Low battery",
    },
    "XMZ": {
        1: "E-01: Voltage anomaly",
        2: "Low battery",
        3: "E-03: Ignition plug anomaly",
        4: "E-04: Oil pump anomaly",
        5: "E-05: Overheat protection",
        6: "E-06: Fan anomaly",
        7: "E-07, Intake air sensor abnormal",
        8: "E-08: Out of fuel, shutdown",
        9: "E-09: Overheat protection sensor",
        10: "E-10: Second startup failed",
        11: "E-11: CO Over limit",
    },
    "JW": {
        0: "E-00, Combustion sensor open circuit",
        1: "E-01, Load short circuit",
        2: "E-02, Power supply voltage too high",
        3: "E-03, Power supply voltage too low",
        4: "E-04, Combustion sensor short circuit (resistance too low)",
        5: "E-05, Overheat sensor open circuit",
        6: "E-06, Overheat sensor short circuit",
        8: "E-08, Electromagnetic pump short circuit",
        13: "E-13, Ignition failure",
        14: "E-14, Combustion flameout",
        18: "E-18, Ignition plug open circuit",
        19: "E-19, Ignition plug short circuit",
        21: "E-21, Main motor short circuit",
        25: "E-25, Atmospheric pressure sensor output voltage too low",
        26: "E-26, Atmospheric pressure sensor output voltage too high",
        27: "E-27, Heater overheating",
        29: "E-29, Main motor not rotating",
        32: (
            "E-32, heater control abnormal. Possible causes: switch damage, heater controller damage, "
            "or wiring harness issue between switch and heater controller"
        ),
    },
    "TWX": {
        1: "E-01: Startup failed",
        2: "E-02: Out of fuel, shutdown",
        3: "E-03: Voltage anomaly",
        4: "E-04: Exhaust sensor anomaly",
        6: "E-06: Intake sensor anomaly",
        7: "E-07: Oil pump anomaly",
        8: "E-08: Fan anomaly",
        9: "E-09: Ignition plug anomaly",
        10: "E-10: Overheat protection",
        11: "E-11: Heater temperature sensor anomaly",
    },
}

# AirHeaterBLE 1.2.0 errtext1; Sunster2.2.000 XMZ fills its blank slots2/7.
AA66_ERROR_NAMES = {
    1: "Voltage fault",
    2: "Low battery",
    3: "Ignition unit fault",
    4: "Fuel pump fault",
    5: "Overheating",
    6: "Fan fault",
    7: "Intake air sensor fault",
    8: "Lack of fuel / flameout",
    9: "Overheat sensor fault",
    10: "Second startup failure",
    11: "CO warning",
}


def error_name(coordinator) -> str | None:
    """Select only the table belonging to the validated protocol/controller."""
    data = coordinator.data
    error = data.get("error_code")
    if not isinstance(error, int) or isinstance(error, bool) or error < 0:
        return None
    mode = coordinator.protocol_mode
    if error == 0 and not (mode == 7 and data.get("hcalory_status") == 15):
        return "No fault"
    if coordinator.is_dz06_neo is True or coordinator.is_warm_drive_controller is True:
        # The saved water UI does not establish air-heater fault descriptions.
        if data.get("neo_controller_type") == "air":
            label = WARM_DRIVE_ERROR_NAMES.get(error)
            return f"E{error:02d} - {label}" if label else f"Unknown error ({error})"
        return f"E{error:02d}"
    if mode == 8:
        return HEATGENIE_ERROR_NAMES.get(error, f"Unknown error ({error})")
    if mode == 7:
        if data.get("hcalory_error_extended") is True:
            major, minor = error >> 4, error & 15
            return f"E{major:02d}" + (str(minor) if minor else "")
        # q2/h.D default formatter uses a literal leading zero except for10/11.
        return f"E{error}" if error in (10, 11) else f"E0{error}"
    if mode == 5:
        return ABBA_ERROR_NAMES.get(error, f"Unknown error ({error})")
    if mode in (0, 1, 2) and data.get("motherboard_version") != 6:
        return ERROR_NAMES.get(error, f"Unknown error ({error})")
    family = data.get("error_family")
    if mode == 6 or family in ("JW", "TY", "TWX"):
        number = 0 if family == "JW" and error == 33 else error
        label = SUNSTER_ERROR_NAMES.get(family, {}).get(number)
        if label:
            return label if label.startswith("E") else f"E{number:02d} - {label}"
        return f"Unknown error ({error}, family={family})"
    if mode in (3, 4):
        if family not in (None, "XMZ"):
            return f"Unknown error ({error}, family={family})"
        label = AA66_ERROR_NAMES.get(error)
        return f"E{error:02d} - {label}" if label else f"Unknown error ({error})"
    if mode in (0, 1, 2):
        return ERROR_NAMES.get(error, f"Unknown error ({error})")
    return f"Unknown error ({error})"
