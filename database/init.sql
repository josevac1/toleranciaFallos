CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    event_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
    event_id INTEGER PRIMARY KEY,
    available_seats INTEGER NOT NULL CHECK (available_seats >= 0),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_inventory_event
        FOREIGN KEY (event_id)
        REFERENCES events(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reservations (
    id UUID PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    event_id INTEGER NOT NULL,
    email VARCHAR(150) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    payment_id UUID,
    status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_reservation_event
        FOREIGN KEY (event_id)
        REFERENCES events(id)
);

INSERT INTO events (
    id,
    name,
    event_date
)
VALUES (
    1,
    'Concierto Sistemas Distribuidos 2026',
    '2026-08-15 19:00:00'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO inventory (
    event_id,
    available_seats
)
VALUES (
    1,
    10
)
ON CONFLICT (event_id) DO NOTHING;

SELECT setval(
    pg_get_serial_sequence('events', 'id'),
    COALESCE((SELECT MAX(id) FROM events), 1)
);

