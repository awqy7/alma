from dataclasses import dataclass
from engine.ipc.contracts import AlmaError, ErrorCode


@dataclass(frozen=True)
class SelectorFallback:
    primary: str
    fallbacks: tuple[str, ...] = ()
    semantic_label: str | None = None
    expected_type: str | tuple[str, ...] = "input"
    required: bool = False
    version_observed: str = "recorder-2026-10-08"


EPROC_SELECTORS = {
    "process_number": "#txtNumProcesso", "filing_date": "#txtDthAjuizamento",
    "total_value": "#txtValorTotal", "principal": "#txtValorPrincipal",
    "selic": "#txtValorParcelaSelic", "interest": "#txtValorJuros",
    "base_date": "#txtDtaBase", "gross_value": "#txtValorBruto",
    "gross_principal": "#txtValorBrutoPrincipal", "gross_selic_interest": "#txtValorBrutoJurosSelic",
    "gross_selic_installment": "#txtValorBrutoParcelaSelic",
    "contractual_percentage": "#txtPercentualContratual", "contractual_minimum": "#txtMinimoContratual",
    "fee_total": "#txtValorTotalHono", "fee_principal": "#txtValorPrincipalHono",
    "fee_selic": "#txtValorParcelaSelicHono", "fee_interest": "#txtValorJurosHono",
    "fee_base_date": "#txtDtaBaseHono", "subform_frame": "#ifrSubFrm",
    "pdf_container": "#conteudoIframe", "beneficiary_container": "#divConteudoBeneficiarios",
    "subject": "#txtDesAssuntoJudicial", "transition_date": "#txtDthTransitoJulgConhec",
    "entity": "#selPessoaRequerido", "requisition_id": "#txtNumRequisicao",
    "beneficiary_name": "#txtNomeBenefi", "beneficiary_tax_id": "#txtCpfCnpjBenefi",
    "save_button": "#btnSalvar",
    "beneficiary_new": "#fldBeneficiarios > legend > span:nth-of-type(2) > a",
    "beneficiary_save": "#btnSalvarFecharBeneficiario",
    "fee_new": "#legHonorarios > span:nth-of-type(2) > a",
    "fee_save": "#btnSalvarFecharHonorario",
    "fee_type": "#selNumCodTipoHonorario",
    "fee_container": "#divConteudoHonorarios",
}


class SelectorRegistry:
    def __init__(self):
        self.entries = {
            key: SelectorFallback(value, required=key in {"process_number", "total_value"},
                expected_type="select" if key == "entity" else "iframe" if key == "subform_frame"
                else "div" if key in {"pdf_container", "beneficiary_container"} else "input")
            for key, value in EPROC_SELECTORS.items()
        }
        # Variants observed across eproc tribunals and actions (cadastrar vs editar).
        self.entries['process_number'] = SelectorFallback(
            '#txtNumProcessoOrigem',
            ('#txtNumProcessoView', '#txtNumProcesso'),
            required=True
        )
        self.entries['requisition_id'] = SelectorFallback(
            '#numIdOficioRequisitorio',
            ('#txtNumRequisicao', '#hdnIdOficioRequisitorio', 'input[name="numIdOficioRequisitorio"]'),
            required=False
        )
        self.entries['entity'] = SelectorFallback('#txtPessoaRequerido', ('#selPessoaRequerido',), expected_type=('input', 'select'))
        self.entries['transition_date'] = SelectorFallback('#txtDthTransitoJulgConhec', ('#txtDthTransitoJef',))

    async def resolve(self, scope, key):
        spec = self.entries[key]
        for selector in (spec.primary, *spec.fallbacks):
            result = await self._single(scope.locator(selector), spec)
            if result is not None:
                return result
        if spec.semantic_label:
            result = await self._single(scope.get_by_label(spec.semantic_label, exact=True), spec)
            if result is not None:
                return result
        if spec.required:
            raise AlmaError(ErrorCode.UI_CHANGED, "selectors")
        return None

    async def _single(self, locator, spec):
        count = await locator.count()
        if count > 1:
            raise AlmaError(ErrorCode.FIELD_AMBIGUOUS, "selectors")
        if count == 1:
            tag = await locator.evaluate("el => el.tagName.toLowerCase()")
            if tag not in (spec.expected_type if isinstance(spec.expected_type,tuple) else (spec.expected_type,)):
                raise AlmaError(ErrorCode.UI_CHANGED, "selectors")
            return locator
        return None


@dataclass(frozen=True)
class PageFingerprint:
    """Structural checks, without storing HTML or user data."""
    required: tuple[str, ...] = ("process_number", "total_value")

    async def verify(self, scope, registry):
        for key in self.required:
            if await registry.resolve(scope, key) is None:
                raise AlmaError(ErrorCode.UI_CHANGED, "fingerprint")
