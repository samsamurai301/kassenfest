"""German labels of the form fields, as printed on the forms: for the viewer and for prompts."""

LABELS = {
    "payer_name": "Krankenkasse bzw. Kostenträger",
    "payer_ik": "Kostenträgerkennung",
    "patient_name": "Name, Vorname des Versicherten",
    "patient_dob": "geb. am",
    "kvnr": "Versicherten-Nr.",
    "bsnr": "Betriebsstätten-Nr.",
    "lanr": "Arzt-Nr.",
    "issue_date": "Datum",
    "icd_codes": "Diagnose(n) (ICD-10)",
    "prescription_kind": "Erst-/Folgeverordnung",
    "accident": "Unfall, Unfallfolgen",
    "blank_prescription": "Blankoverordnung",
    "period_from": "vom",
    "period_to": "bis",
    "further_notes": "Weitere Hinweise",
    "doctor_signature": "Unterschrift des Arztes",
    "practice_stamp": "Vertragsarztstempel",
    "corrections_initialled": "Korrektur abgezeichnet",
    "letter_date": "Datum des Schreibens",
    "approval_ref": "Genehmigungskennzeichen",
    "provider_name": "Pflegedienst",
    "provider_ik": "IK Pflegedienst",
    "prescription_issue_date": "Verordnung vom",
    "decision": "Entscheidung",
    "month": "Monat",
    "responsible_nurse": "Verantwortliche Pflegefachkraft",
    "patient_signature": "Unterschrift Versicherte/r",
    "patient_signature_date": "Datum der Unterschrift",
    "missing_signature_reason": "Kennzeichen fehlende Unterschrift",
    "provider_signature": "Unterschrift / Stempel Pflegedienst",
    "pflegegrad": "Pflegegrad",
    "hospital_name": "Krankenhaus",
    "hospital_id": "Standortkennzeichen",
    "admission_date": "Aufnahme",
    "admission_time": "Aufnahme, Uhrzeit",
    "discharge_date": "Entlassung",
    "discharge_time": "Entlassung, Uhrzeit",
    "discharge_diagnoses": "Entlassdiagnosen",
    "hkp_recommended": "Häusliche Krankenpflege empfohlen",
    "hkp_prescription_days": "HKP-Tage verordnet",
    "physician_signature": "Unterschrift Arzt",
}

ROWS = {
    "measures": "Maßnahme",
    "approved_items": "Genehmigt",
    "rejected_items": "Abgelehnt",
    "entries": "Zeile",
}
"""List fields: the label of one row, numbered from 1."""


def field_label(path: str) -> str:
    """'period_to' -> 'bis'; 'entries[3].start_time' -> 'Zeile 4, start_time'."""
    head, _, rest = path.partition(".")
    name, _, index = head.partition("[")
    if index and name in ROWS:
        row = f"{ROWS[name]} {int(index.rstrip(']')) + 1}"
        return f"{row}, {LABELS.get(rest, rest)}" if rest else row
    return LABELS.get(path, path)
