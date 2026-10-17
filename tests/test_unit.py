"""Unit tests of validation and the renewal business rule, without a database."""

from datetime import date

import pytest

from app import APIError, integer, renewal_due_date, string


@pytest.mark.parametrize('value', [1450, 2100])
def test_year_accepts_both_boundaries(value):
    assert integer({'year': value}, 'year', 1450, 2100) == value


def test_boolean_is_not_a_positive_integer_identifier():
    with pytest.raises(APIError) as error:
        integer({'id': True}, 'id')
    assert error.value.status == 422


@pytest.mark.parametrize('value', [1449, 2101, True, 2020.0, '2020', None])
def test_year_rejects_outside_range_and_wrong_types(value):
    with pytest.raises(APIError) as error:
        integer({'year': value}, 'year', 1450, 2100)
    assert error.value.status == 422


def test_string_trims_and_validates_length():
    assert string({'name': '  Имя  '}, 'name', 3, 3) == 'Имя'
    for value in ('', '  ', 'xx', 'xxxx', 42, [], None):
        with pytest.raises(APIError):
            string({'name': value}, 'name', 3, 3)


def test_renew_from_previous_due_date():
    assert renewal_due_date('2026-10-20', None, 0, date(2026, 10, 17), 14) == '2026-11-03'


def test_renew_on_due_date_is_allowed():
    assert renewal_due_date('2026-10-17', None, 0, date(2026, 10, 17), 14) == '2026-10-31'


@pytest.mark.parametrize(
    'due,returned,count',
    [
        ('2026-10-16', None, 0),
        ('2026-10-20', '2026-10-17', 0),
        ('2026-10-20', None, 1),
    ],
)
def test_renew_rejects_overdue_returned_and_second_renewal(due, returned, count):
    with pytest.raises(APIError) as error:
        renewal_due_date(due, returned, count, date(2026, 10, 17), 14)
    assert error.value.status == 409
