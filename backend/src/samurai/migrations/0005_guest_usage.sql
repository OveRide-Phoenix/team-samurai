CREATE TABLE "{{schema}}".samurai_guest_usage (
    day date NOT NULL,
    actor_id text NOT NULL,
    writes integer NOT NULL DEFAULT 0 CHECK (writes >= 0),
    ai_runs integer NOT NULL DEFAULT 0 CHECK (ai_runs >= 0),
    PRIMARY KEY (day, actor_id)
);
