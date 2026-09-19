PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS faculties (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE CHECK(length(trim(name)) BETWEEN 1 AND 120)
);
CREATE TABLE IF NOT EXISTS branches (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authors (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS books (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, author_id INTEGER NOT NULL REFERENCES authors(id),
 year INTEGER NOT NULL CHECK(year BETWEEN 1450 AND 2100), isbn TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS copies (
 id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
 branch_id INTEGER NOT NULL REFERENCES branches(id), inventory_number TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 full_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('reader','librarian')),
 faculty_id INTEGER REFERENCES faculties(id)
);
CREATE TABLE IF NOT EXISTS loans (
 id INTEGER PRIMARY KEY, copy_id INTEGER NOT NULL REFERENCES copies(id),
 reader_id INTEGER NOT NULL REFERENCES users(id), issued_at TEXT NOT NULL,
 due_at TEXT NOT NULL, returned_at TEXT,
 CHECK(due_at >= issued_at), CHECK(returned_at IS NULL OR returned_at >= issued_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan_per_copy ON loans(copy_id) WHERE returned_at IS NULL;
CREATE INDEX IF NOT EXISTS loans_reader ON loans(reader_id, returned_at);
CREATE INDEX IF NOT EXISTS copies_book ON copies(book_id, branch_id);
CREATE INDEX IF NOT EXISTS books_author ON books(author_id);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
 entity TEXT NOT NULL, entity_id INTEGER, created_at TEXT NOT NULL
);
