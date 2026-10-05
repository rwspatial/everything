-- migrate:up
-- Settlements method v4 (Degree of Urbanisation, docs/methods/settlements.json) classifies settlements by character as
-- well as size, so an edit's class override follows: size_class -> settlement_class, with the new classes. Old values
-- map to their nearest new class.
ALTER TABLE app.settlement_edits DROP CONSTRAINT settlement_edits_size_class_check;
ALTER TABLE app.settlement_edits RENAME COLUMN size_class TO settlement_class;
UPDATE app.settlement_edits SET settlement_class = CASE settlement_class
    WHEN 'City or large town' THEN 'City' WHEN 'Town centre' THEN 'Town' ELSE settlement_class END;
ALTER TABLE app.settlement_edits ADD CONSTRAINT settlement_edits_settlement_class_check CHECK (
    settlement_class IS NULL
    OR settlement_class IN ('City', 'Town', 'Suburb', 'Village', 'Hamlet', 'Roadside strip'));

-- migrate:down
ALTER TABLE app.settlement_edits DROP CONSTRAINT settlement_edits_settlement_class_check;
UPDATE app.settlement_edits SET settlement_class = CASE settlement_class
    WHEN 'City' THEN 'City or large town' WHEN 'Town' THEN 'Town centre' WHEN 'Suburb' THEN 'Town centre'
    WHEN 'Roadside strip' THEN 'Hamlet' ELSE settlement_class END;
ALTER TABLE app.settlement_edits RENAME COLUMN settlement_class TO size_class;
ALTER TABLE app.settlement_edits ADD CONSTRAINT settlement_edits_size_class_check CHECK (
    size_class IS NULL OR size_class IN ('City or large town', 'Town centre', 'Village', 'Hamlet'));
