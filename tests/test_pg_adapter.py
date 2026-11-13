import unittest
from types import SimpleNamespace

try:
    from pg_adapter import row_factory
except ImportError:
    row_factory = None


@unittest.skipIf(row_factory is None, 'psycopg is optional for SQLite')
class PostgresAdapterTests(unittest.TestCase):
    def test_row_factory_for_statements_without_results(self):
        self.assertEqual(row_factory(SimpleNamespace(description=None))(()), {})

    def test_row_supports_names_and_indexes(self):
        cursor = SimpleNamespace(description=[SimpleNamespace(name='id'), SimpleNamespace(name='name')])
        row = row_factory(cursor)((7, 'example'))
        self.assertEqual((row['name'], row[0]), ('example', 7))
