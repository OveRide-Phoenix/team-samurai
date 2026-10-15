ALTER TABLE "{{schema}}".samurai_learning_records
    ADD COLUMN shared boolean NOT NULL DEFAULT false;

ALTER TABLE "{{schema}}".samurai_learning_records
    ADD CONSTRAINT samurai_learning_shared_correction
    CHECK (NOT shared OR kind = 'correction');
