-- Requires PostGIS extension for geospatial queries:
-- CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS trucks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    cuisine_type TEXT,
    social_links TEXT[],
    average_confidence_score FLOAT DEFAULT 0.0,
    menu_highlights TEXT[],
    image_url TEXT,
    is_claimed BOOLEAN DEFAULT FALSE,
    owner_user_id UUID,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT NOT NULL,
    home_city TEXT,
    reputation_score INT DEFAULT 0,
    notifications_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS favorites (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    truck_id UUID REFERENCES trucks(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, truck_id)
);

CREATE TABLE IF NOT EXISTS sightings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id UUID REFERENCES trucks(id) ON DELETE CASCADE,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    reported_by_user_id UUID REFERENCES users(id),
    photo_url TEXT,
    note TEXT,
    confidence_level TEXT CHECK (confidence_level IN ('confirmed','likely','scheduled')),
    timestamp TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,
    source TEXT DEFAULT 'crowdsource' -- crowdsource | social | permit
);

CREATE TABLE IF NOT EXISTS scheduled_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id UUID REFERENCES trucks(id) ON DELETE CASCADE,
    source TEXT, -- e.g. 'instagram', 'city_permit_feed'
    extracted_location TEXT,
    extracted_latitude DOUBLE PRECISION,
    extracted_longitude DOUBLE PRECISION,
    extracted_time TIMESTAMPTZ,
    raw_source_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sightings_truck_id ON sightings(truck_id);
CREATE INDEX IF NOT EXISTS idx_sightings_expires_at ON sightings(expires_at);


CREATE TABLE IF NOT EXISTS radar_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id UUID REFERENCES trucks(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ DEFAULT now(),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    text TEXT,
    source_url TEXT,
    raw_confidence DOUBLE PRECISION DEFAULT 0.5,
    state TEXT DEFAULT 'live',
    metadata JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_radar_observations_truck_time ON radar_observations(truck_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_radar_observations_source ON radar_observations(source, observed_at DESC);

CREATE TABLE IF NOT EXISTS prediction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id UUID REFERENCES trucks(id) ON DELETE CASCADE,
    predicted_latitude DOUBLE PRECISION,
    predicted_longitude DOUBLE PRECISION,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    confidence DOUBLE PRECISION,
    model_version TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prediction_runs_truck_time ON prediction_runs(truck_id, created_at DESC);


-- ============================================================
-- PHASE: MENU + ORDER (Postgres reference schema)
--
-- NOTE: production reads/writes go through CloudKit (see
-- cloudkit_bridge.py + cloudkit_schema.txt for the live equivalents
-- of these tables — MenuItem / Order / OrderItem record types).
-- This Postgres schema is kept as the canonical relational reference
-- (for the Vercel Postgres / analytics path, and in case the project
-- ever needs to migrate off CloudKit) so both stores agree on shape.
-- ============================================================

CREATE TABLE IF NOT EXISTS menus (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id UUID NOT NULL REFERENCES trucks(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT 'Main Menu',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_menus_truck_id ON menus(truck_id);

CREATE TABLE IF NOT EXISTS menu_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_id UUID NOT NULL REFERENCES menus(id) ON DELETE CASCADE,
    truck_id UUID NOT NULL REFERENCES trucks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT CHECK (category IN ('entree','side','drink','dessert','combo','special')) DEFAULT 'entree',
    price_cents INT NOT NULL CHECK (price_cents >= 0),
    currency TEXT DEFAULT 'USD',
    photo_url TEXT,
    is_available BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    modifiers JSONB DEFAULT '[]'::jsonb, -- [{"name": "Extra spicy", "priceDeltaCents": 0}, ...]
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_menu_items_menu_id ON menu_items(menu_id);
CREATE INDEX IF NOT EXISTS idx_menu_items_truck_id ON menu_items(truck_id);

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id UUID NOT NULL REFERENCES trucks(id) ON DELETE CASCADE,
    customer_user_id UUID REFERENCES users(id),
    customer_name TEXT,
    status TEXT CHECK (status IN (
        'pending', 'accepted', 'preparing', 'ready', 'completed', 'cancelled'
    )) DEFAULT 'pending',
    subtotal_cents INT NOT NULL DEFAULT 0,
    tax_cents INT NOT NULL DEFAULT 0,
    tip_cents INT NOT NULL DEFAULT 0,
    total_cents INT NOT NULL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    special_instructions TEXT,
    pickup_eta_minutes INT,
    payment_provider TEXT, -- 'stripe' | 'square'
    payment_intent_id TEXT,
    payment_status TEXT CHECK (payment_status IN (
        'unpaid', 'authorized', 'captured', 'refunded', 'failed'
    )) DEFAULT 'unpaid',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_orders_truck_status ON orders(truck_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_truck_created ON orders(truck_id, created_at DESC);

CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id UUID REFERENCES menu_items(id),
    name_snapshot TEXT NOT NULL,       -- item name at time of order (menu can change later)
    unit_price_cents INT NOT NULL,     -- price at time of order
    quantity INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
    modifiers JSONB DEFAULT '[]'::jsonb,
    line_total_cents INT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
