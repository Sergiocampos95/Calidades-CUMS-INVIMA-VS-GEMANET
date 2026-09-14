-- Modulo de acceso de esta app en el modelo de permisos compartido con el
-- dashboard de Auditoria de Calidades (auditoria_calidades/ddl/07_acceso_modulos.sql).
-- Los administradores del ERP (usuario.sw_administrador = 1) entran sin modulo;
-- el resto lo recibe desde /admin/permisos de ese dashboard.
-- Ejecutar UNA vez con el rol de la app (dueno de aud_app_modulo):
--   psql "$GEMANET_DB_DSN" -f ddl/01_modulo_cums.sql
INSERT INTO administrativo.aud_app_modulo (id_modulo, nombre, sw_activo, descripcion)
VALUES (
    'CUMS',
    'Calidades CUMS (INVIMA vs Gemma Net)',
    1,
    'Auditoria de los medicamentos CUM de Gemma Net contra los listados de INVIMA. App en el puerto 8870.'
)
ON CONFLICT (id_modulo) DO NOTHING;
