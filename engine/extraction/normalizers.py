"""Strict input normalization. Ambiguous formats raise instead of guessing."""
import re
from datetime import datetime
from decimal import Decimal


def money(raw: str) -> Decimal:
    value = raw.strip().removeprefix("R$").strip()
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{2})?", value):
        raise ValueError("Invalid BRL")
    return Decimal(value.replace(".", "").replace(",", ".")).quantize(Decimal("0.01"))


def date(raw: str) -> str:
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw.strip()):
        raise ValueError("Invalid date")
    return datetime.strptime(raw.strip(), "%d/%m/%Y").date().isoformat()


def tax_id(raw: str) -> str:
    if not re.fullmatch(r"[\d. /-]+", raw.strip()):
        raise ValueError("Invalid CPF/CNPJ")
    value = re.sub(r"\D", "", raw)
    if len(value) not in (11, 14):
        raise ValueError("Invalid CPF/CNPJ length")
    return value


def percentage(raw: str) -> Decimal:
    value = raw.strip().removesuffix("%").strip()
    if not re.fullmatch(r"\d+(?:,\d+)?", value):
        raise ValueError("Invalid percentage")
    return Decimal(value.replace(",", "."))


def boolean(raw: str) -> bool:
    value = raw.strip().casefold()
    if value in {"sim", "s", "true"}:
        return True
    if value in {"não", "nao", "n", "false"}:
        return False
    raise ValueError("Invalid boolean")
