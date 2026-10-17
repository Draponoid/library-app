-- depends: 0002_indexes
ALTER TABLE loans ADD COLUMN renewal_count INTEGER NOT NULL DEFAULT 0 CHECK(renewal_count BETWEEN 0 AND 1);
