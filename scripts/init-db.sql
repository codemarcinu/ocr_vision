-- Smart Pantry Tracker Database Schema
-- PostgreSQL 16 with pg_trgm for fuzzy matching

-- Extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Kategorie produktów
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    key VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wstępne kategorie
INSERT INTO categories (key, name) VALUES
    ('nabial', 'Nabiał'),
    ('pieczywo', 'Pieczywo'),
    ('mieso', 'Mięso i wędliny'),
    ('warzywa', 'Warzywa i owoce'),
    ('napoje', 'Napoje'),
    ('slodycze', 'Słodycze'),
    ('suche', 'Produkty suche'),
    ('mrozonki', 'Mrożonki'),
    ('chemia', 'Chemia'),
    ('inne', 'Inne');

-- Sklepy
CREATE TABLE stores (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Aliasy sklepów (dla OCR)
CREATE TABLE store_aliases (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,
    alias VARCHAR(100) UNIQUE NOT NULL
);
CREATE INDEX idx_store_aliases_trgm ON store_aliases USING gin(alias gin_trgm_ops);

-- Produkty (słownik znormalizowanych nazw)
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    normalized_name VARCHAR(200) NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    typical_price_pln DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(normalized_name, category_id)
);
CREATE INDEX idx_products_trgm ON products USING gin(normalized_name gin_trgm_ops);
CREATE INDEX idx_products_category ON products(category_id);

-- Warianty nazw produktów (raw nazwy z OCR)
CREATE TABLE product_variants (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    raw_name VARCHAR(300) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_variants_trgm ON product_variants USING gin(raw_name gin_trgm_ops);
CREATE INDEX idx_variants_product ON product_variants(product_id);

-- Skróty produktów (specyficzne dla sklepu, np. termiczne drukarki Biedronki)
CREATE TABLE product_shortcuts (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,
    shortcut VARCHAR(100) NOT NULL,
    full_name VARCHAR(300) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id, shortcut)
);
CREATE INDEX idx_shortcuts_store ON product_shortcuts(store_id);

-- Paragony
CREATE TABLE receipts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_file VARCHAR(255) NOT NULL,
    receipt_date DATE NOT NULL,
    store_id INTEGER REFERENCES stores(id),
    store_raw VARCHAR(200),
    total_ocr DECIMAL(10,2),
    total_calculated DECIMAL(10,2),
    total_final DECIMAL(10,2),
    raw_text TEXT,
    needs_review BOOLEAN DEFAULT FALSE,
    review_reasons TEXT[],
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_receipts_date ON receipts(receipt_date DESC);
CREATE INDEX idx_receipts_store ON receipts(store_id);
CREATE INDEX idx_receipts_source ON receipts(source_file);
CREATE INDEX idx_receipts_needs_review ON receipts(needs_review) WHERE needs_review = TRUE;

-- Pozycje paragonu
CREATE TABLE receipt_items (
    id SERIAL PRIMARY KEY,
    receipt_id UUID REFERENCES receipts(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id),
    name_raw VARCHAR(300) NOT NULL,
    name_normalized VARCHAR(200),
    price_final DECIMAL(10,2) NOT NULL,
    price_original DECIMAL(10,2),
    discount_amount DECIMAL(10,2),
    discount_details JSONB DEFAULT '[]',
    category_id INTEGER REFERENCES categories(id),
    confidence DECIMAL(3,2),
    warning VARCHAR(200),
    match_method VARCHAR(30),
    item_metadata JSONB DEFAULT '{}'
);
CREATE INDEX idx_receipt_items_receipt ON receipt_items(receipt_id);
CREATE INDEX idx_receipt_items_product ON receipt_items(product_id);
CREATE INDEX idx_receipt_items_category ON receipt_items(category_id);

-- Spiżarnia (stan magazynu)
CREATE TABLE pantry_items (
    id SERIAL PRIMARY KEY,
    receipt_item_id INTEGER REFERENCES receipt_items(id) ON DELETE SET NULL,
    product_id INTEGER REFERENCES products(id),
    name VARCHAR(300) NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    store_id INTEGER REFERENCES stores(id),
    purchase_date DATE NOT NULL,
    expiry_date DATE,
    quantity DECIMAL(10,3) DEFAULT 1.0,
    is_consumed BOOLEAN DEFAULT FALSE,
    consumed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_pantry_items_consumed ON pantry_items(is_consumed);
CREATE INDEX idx_pantry_items_category ON pantry_items(category_id);
CREATE INDEX idx_pantry_items_product ON pantry_items(product_id);

-- Historia cen (dla analityki)
CREATE TABLE price_history (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    store_id INTEGER REFERENCES stores(id),
    price DECIMAL(10,2) NOT NULL,
    receipt_id UUID REFERENCES receipts(id) ON DELETE SET NULL,
    recorded_date DATE NOT NULL
);
CREATE INDEX idx_price_history_product ON price_history(product_id, recorded_date DESC);
CREATE INDEX idx_price_history_store ON price_history(store_id);

-- Feedback: produkty nierozpoznane (do nauki)
CREATE TABLE unmatched_products (
    id SERIAL PRIMARY KEY,
    raw_name VARCHAR(300) NOT NULL,
    raw_name_normalized VARCHAR(300) UNIQUE,
    price DECIMAL(10,2),
    store_id INTEGER REFERENCES stores(id),
    first_seen DATE NOT NULL,
    last_seen DATE NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    is_learned BOOLEAN DEFAULT FALSE,
    learned_product_id INTEGER REFERENCES products(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_unmatched_count ON unmatched_products(occurrence_count DESC);
CREATE INDEX idx_unmatched_learned ON unmatched_products(is_learned);

-- Feedback: korekty review
CREATE TABLE review_corrections (
    id SERIAL PRIMARY KEY,
    receipt_id UUID REFERENCES receipts(id) ON DELETE SET NULL,
    original_total DECIMAL(10,2),
    corrected_total DECIMAL(10,2) NOT NULL,
    correction_type VARCHAR(20) NOT NULL,  -- 'approved', 'calculated', 'manual', 'rejected'
    store_id INTEGER REFERENCES stores(id),
    product_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_corrections_receipt ON review_corrections(receipt_id);
CREATE INDEX idx_corrections_type ON review_corrections(correction_type);

-- Funkcja do aktualizacji updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggery dla updated_at
CREATE TRIGGER update_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_unmatched_updated_at
    BEFORE UPDATE ON unmatched_products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Widok: podsumowanie sklepu
CREATE VIEW store_summary AS
SELECT
    s.id,
    s.name,
    COUNT(DISTINCT r.id) as receipt_count,
    SUM(r.total_final) as total_spent,
    MAX(r.receipt_date) as last_visit
FROM stores s
LEFT JOIN receipts r ON s.id = r.store_id
GROUP BY s.id, s.name;

-- Widok: statystyki produktów
CREATE VIEW product_stats AS
SELECT
    p.id,
    p.normalized_name,
    c.name as category,
    COUNT(ri.id) as purchase_count,
    AVG(ri.price_final) as avg_price,
    MIN(ri.price_final) as min_price,
    MAX(ri.price_final) as max_price
FROM products p
LEFT JOIN categories c ON p.category_id = c.id
LEFT JOIN receipt_items ri ON p.id = ri.product_id
GROUP BY p.id, p.normalized_name, c.name;
