"""
A minimal parser for ANSI X12 837P (Professional Claim) files — the format
real clearinghouses and TPAs actually receive claims in.

THIS IS NOT A CERTIFIED, FULL X12 837 IMPLEMENTATION. The real spec has many
optional loops, multiple providers per claim, institutional (837I) claims,
coordination-of-benefits segments, and dozens of segments this doesn't touch.
It covers the common, practical case this app needs: one or more claims
(CLM segments) per file, each with a billing provider (NM1*85), a subscriber
/ patient (NM1*IL), an optional prior-authorization number (REF*G1), and one
or more service lines (SV1, with a DTP*472 for the service date). Treat it
as a solid starting point, not a drop-in replacement for a real EDI gateway.

Segment structure: segments are separated by '~', elements within a segment
by '*', and some elements are themselves composite, separated by ':'
(e.g. "HC:99213" — the procedure code qualifier and the CPT code).

Usage:
    from edi837_parser import parse_837, EDI837ParseError
    claims = parse_837(raw_text)  # -> list of dicts shaped for IngestionInputSerializer
"""

from datetime import datetime


class EDI837ParseError(Exception):
    pass


def _get(elements, index, default=""):
    return elements[index] if len(elements) > index and elements[index] != "" else default


def _split_segments(text: str):
    text = text.strip().replace("\n", "").replace("\r", "")
    segments = []
    for raw_seg in text.split("~"):
        raw_seg = raw_seg.strip()
        if raw_seg:
            segments.append(raw_seg.split("*"))
    return segments


def _parse_date(value: str):
    """D8 format = CCYYMMDD, the standard X12 date format."""
    if not value or len(value) != 8:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_837(text: str) -> list:
    segments = _split_segments(text)
    if not segments or segments[0][0] != "ISA":
        raise EDI837ParseError("File does not start with an ISA segment — not a valid X12 EDI file.")

    claims = []
    current_provider = {"provider_id": "", "name": "", "is_active": True}
    current_member = {"member_id": "", "name": "", "membership_status": "ACTIVE", "membership_effective_date": None}
    current_claim = None

    def close_current_claim():
        if current_claim is None:
            return
        if not current_claim["service_lines"]:
            raise EDI837ParseError(f"Claim {current_claim.get('claim_number')} has no SV1 service line segments.")
        if not current_claim["date_of_service"]:
            for line in current_claim["service_lines"]:
                if line.get("_date"):
                    current_claim["date_of_service"] = line["_date"]
                    break
        for line in current_claim["service_lines"]:
            line.pop("_date", None)
        claims.append(current_claim)

    for elements in segments:
        seg_id = elements[0]

        if seg_id == "NM1":
            entity_id_code = _get(elements, 1)
            if entity_id_code == "85":  # Billing provider
                current_provider = {
                    "provider_id": _get(elements, 9) or _get(elements, 3, "UNKNOWN"),
                    "name": _get(elements, 3, "Unknown Provider"),
                    "is_active": True,
                }
            elif entity_id_code == "IL":  # Subscriber (patient / member)
                last = _get(elements, 3)
                first = _get(elements, 4)
                current_member = {
                    "member_id": _get(elements, 9) or "UNKNOWN",
                    "name": f"{first} {last}".strip() or "Unknown Member",
                    "membership_status": "ACTIVE",  # not carried in an 837; eligibility comes from a 271, not the claim
                    "membership_effective_date": None,
                }

        elif seg_id == "CLM":
            close_current_claim()
            current_claim = {
                "claim_number": _get(elements, 1),
                "claim_type": "",
                "authorization_number": "",
                "date_of_service": None,
                "total_claim_amount": _get(elements, 2, "0"),
                "provider": dict(current_provider),
                "member": dict(current_member),
                "service_lines": [],
            }

        elif seg_id == "REF" and current_claim is not None:
            if _get(elements, 1) == "G1":  # Prior authorization number
                current_claim["authorization_number"] = _get(elements, 2)

        elif seg_id == "SV1" and current_claim is not None:
            composite = _get(elements, 1).split(":")
            cpt_code = composite[1] if len(composite) > 1 else composite[0]
            current_claim["service_lines"].append({
                "cpt_code": cpt_code or "UNKNOWN",
                "description": "",
                "units": _get(elements, 4, "1"),
                "billed_amount": _get(elements, 2, "0"),
                "_date": None,
            })

        elif seg_id == "DTP" and current_claim is not None:
            if _get(elements, 1) == "472":  # Service date
                date_value = _parse_date(_get(elements, 3))
                if current_claim["service_lines"]:
                    current_claim["service_lines"][-1]["_date"] = date_value
                if not current_claim["date_of_service"]:
                    current_claim["date_of_service"] = date_value

    close_current_claim()

    if not claims:
        raise EDI837ParseError("No CLM segments found — this file has no claims to ingest.")

    return claims