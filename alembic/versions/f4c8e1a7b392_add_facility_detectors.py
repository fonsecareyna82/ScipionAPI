"""Give each facility microscope its detectors, each with its gain and calibrated pixel sizes.

A microscope may have several cameras (a Falcon and a Ceta, a K3 behind an
energy filter), each with its own gain reference and orientation, and its own
pixel size at a given magnification. The name the acquisition metadata gives a
detector (EPU writes BM-Falcon, EF-CCD...) tells which one took a movie. The gain and the calibration move from
the microscope to its detectors. What there was is kept: the microscope's
detectors text gives one detector per name (split at commas), and the first
one takes the microscope's gain and calibrated pixel sizes.

Revision ID: f4c8e1a7b392
Revises: e3a6c9d2f458
"""
from alembic import op


revision = "f4c8e1a7b392"
down_revision = "e3a6c9d2f458"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_detectors (
            id SERIAL PRIMARY KEY,
            "microscopeId" INTEGER NOT NULL REFERENCES facility_microscopes(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            "metadataName" TEXT NOT NULL DEFAULT '',
            "energyFiltered" BOOLEAN NOT NULL DEFAULT FALSE,
            "gainPath" TEXT NOT NULL DEFAULT '',
            "gainFlip" TEXT NOT NULL DEFAULT 'none',
            "gainRotation" INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            CONSTRAINT ux_facility_detectors_name UNIQUE ("microscopeId", name) DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT ck_facility_detectors_gain_flip CHECK ("gainFlip" IN ('none', 'horizontal', 'vertical')),
            CONSTRAINT ck_facility_detectors_gain_rotation CHECK ("gainRotation" IN (0, 90, 180, 270))
        )
    """)
    op.execute("""
        CREATE TABLE facility_detector_pixel_sizes (
            "detectorId" INTEGER NOT NULL REFERENCES facility_detectors(id) ON DELETE CASCADE,
            magnification INTEGER NOT NULL,
            "pixelSize" DOUBLE PRECISION NOT NULL,
            PRIMARY KEY ("detectorId", magnification),
            CONSTRAINT ck_facility_detector_pixel_sizes_positive CHECK (magnification > 0 AND "pixelSize" > 0)
        )
    """)
    # One detector per name of the old text; the first takes the microscope's gain and calibration
    op.execute("""
        INSERT INTO facility_detectors ("microscopeId", name, "gainPath", "gainFlip", "gainRotation")
        SELECT id, name, "gainPath", "gainFlip", "gainRotation" FROM (
            SELECT DISTINCT ON (m.id, TRIM(part.name)) m.id, TRIM(part.name) AS name, part.n,
                   CASE WHEN part.n = 1 THEN m."gainPath" ELSE '' END AS "gainPath",
                   CASE WHEN part.n = 1 THEN m."gainFlip" ELSE 'none' END AS "gainFlip",
                   CASE WHEN part.n = 1 THEN m."gainRotation" ELSE 0 END AS "gainRotation"
              FROM facility_microscopes m,
                   LATERAL UNNEST(STRING_TO_ARRAY(m.detectors, ',')) WITH ORDINALITY AS part(name, n)
             WHERE TRIM(part.name) <> ''
             ORDER BY m.id, TRIM(part.name), part.n
        ) named ORDER BY id, n
    """)
    op.execute("""
        INSERT INTO facility_detectors ("microscopeId", name, "gainPath", "gainFlip", "gainRotation")
        SELECT m.id, 'Camera', m."gainPath", m."gainFlip", m."gainRotation"
          FROM facility_microscopes m
         WHERE NOT EXISTS (SELECT 1 FROM facility_detectors d WHERE d."microscopeId" = m.id)
           AND (m."gainPath" <> '' OR EXISTS (SELECT 1 FROM facility_microscope_pixel_sizes p
                                               WHERE p."microscopeId" = m.id))
    """)
    op.execute("""
        INSERT INTO facility_detector_pixel_sizes ("detectorId", magnification, "pixelSize")
        SELECT first.id, p.magnification, p."pixelSize"
          FROM facility_microscope_pixel_sizes p
          JOIN LATERAL (SELECT d.id FROM facility_detectors d WHERE d."microscopeId" = p."microscopeId"
                         ORDER BY d.id LIMIT 1) first ON TRUE
    """)
    op.execute("DROP TABLE facility_microscope_pixel_sizes")
    op.execute('ALTER TABLE facility_microscopes DROP COLUMN detectors, DROP COLUMN "gainPath", '
               'DROP COLUMN "gainFlip", DROP COLUMN "gainRotation"')


def downgrade():
    op.execute("""
        ALTER TABLE facility_microscopes
            ADD COLUMN detectors TEXT NOT NULL DEFAULT '',
            ADD COLUMN "gainPath" TEXT NOT NULL DEFAULT '',
            ADD COLUMN "gainFlip" TEXT NOT NULL DEFAULT 'none',
            ADD COLUMN "gainRotation" INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE facility_microscopes
            ADD CONSTRAINT ck_facility_microscopes_gain_flip CHECK ("gainFlip" IN ('none', 'horizontal', 'vertical')),
            ADD CONSTRAINT ck_facility_microscopes_gain_rotation CHECK ("gainRotation" IN (0, 90, 180, 270))
    """)
    op.execute("""
        CREATE TABLE facility_microscope_pixel_sizes (
            "microscopeId" INTEGER NOT NULL REFERENCES facility_microscopes(id) ON DELETE CASCADE,
            magnification INTEGER NOT NULL,
            "pixelSize" DOUBLE PRECISION NOT NULL,
            PRIMARY KEY ("microscopeId", magnification),
            CONSTRAINT ck_facility_microscope_pixel_sizes_positive CHECK (magnification > 0 AND "pixelSize" > 0)
        )
    """)
    # Back to one text and one table: the first detector gives the gain and the calibration
    op.execute("""
        UPDATE facility_microscopes m
           SET detectors = COALESCE((SELECT STRING_AGG(d.name, ', ' ORDER BY d.id)
                                       FROM facility_detectors d WHERE d."microscopeId" = m.id), ''),
               "gainPath" = COALESCE(first."gainPath", ''),
               "gainFlip" = COALESCE(first."gainFlip", 'none'),
               "gainRotation" = COALESCE(first."gainRotation", 0)
          FROM (SELECT DISTINCT ON ("microscopeId") "microscopeId", "gainPath", "gainFlip", "gainRotation"
                  FROM facility_detectors ORDER BY "microscopeId", id) first
         WHERE first."microscopeId" = m.id
    """)
    op.execute("""
        INSERT INTO facility_microscope_pixel_sizes ("microscopeId", magnification, "pixelSize")
        SELECT d."microscopeId", p.magnification, p."pixelSize"
          FROM facility_detector_pixel_sizes p
          JOIN (SELECT DISTINCT ON ("microscopeId") id, "microscopeId" FROM facility_detectors
                 ORDER BY "microscopeId", id) d ON d.id = p."detectorId"
    """)
    op.execute("DROP TABLE IF EXISTS facility_detector_pixel_sizes")
    op.execute("DROP TABLE IF EXISTS facility_detectors")
