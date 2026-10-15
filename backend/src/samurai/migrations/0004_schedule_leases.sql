ALTER TABLE "{{schema}}".samurai_schedules
    ALTER COLUMN next_run_at DROP NOT NULL;

ALTER TABLE "{{schema}}".samurai_schedule_runs
    ADD COLUMN lease_owner text,
    ADD COLUMN lease_expires_at bigint;

UPDATE "{{schema}}".samurai_schedule_runs
SET lease_owner = 'migration-recovery', lease_expires_at = 0
WHERE status = 'claimed';

ALTER TABLE "{{schema}}".samurai_schedule_runs
    ADD CONSTRAINT samurai_schedule_runs_lease_state CHECK (
        (status = 'claimed' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'claimed' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    );

CREATE INDEX idx_samurai_schedule_runs_expired_lease
    ON "{{schema}}".samurai_schedule_runs(lease_expires_at)
    WHERE status = 'claimed';
