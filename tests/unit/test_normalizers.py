from decimal import Decimal
import pytest
from engine.extraction.normalizers import money, date, tax_id, percentage, boolean


@pytest.mark.parametrize('raw,expected', [('R$ 8.957,93','8957.93'), ('2.400,00','2400.00'), ('0','0.00'), ('-1,25','-1.25')])
def test_brl(raw, expected):
    assert money(raw) == Decimal(expected)


@pytest.mark.parametrize('raw', ['8,957.93', '1.23', 'NaN', '', '10,001', 'R$ 1 ou 2'])
def test_ambiguous_money_rejected(raw):
    with pytest.raises(ValueError): money(raw)


def test_other_normalizers():
    assert date('29/02/2024') == '2024-02-29'
    with pytest.raises(ValueError): date('29/02/2025')
    assert tax_id('000.000.000-00') == '00000000000'
    assert percentage('20%') == Decimal('20')
    assert percentage('2,5%') == Decimal('2.5')
    for raw in ['NÃO', 'Não', 'N', 'false']: assert boolean(raw) is False
    assert boolean('SIM') is True
    with pytest.raises(ValueError): boolean('talvez')
