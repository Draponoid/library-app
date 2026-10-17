-- depends: 0001_initial
CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan_per_copy ON loans(copy_id) WHERE returned_at IS NULL;
CREATE INDEX IF NOT EXISTS loans_reader ON loans(reader_id, returned_at);
CREATE INDEX IF NOT EXISTS copies_book ON copies(book_id, branch_id);
CREATE INDEX IF NOT EXISTS books_author ON books(author_id);
