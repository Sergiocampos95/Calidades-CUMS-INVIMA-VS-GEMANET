# Frontend -- Fase 3 de la migracion fuera de Streamlit

Vite + TypeScript, sin framework (ver `.claude/plans` para la justificacion:
la superficie real -- candidatos, auditoria, salud -- no justifica React/JSX
para un equipo chico).

## Arrancar en desarrollo

```bash
cd backend && uvicorn app.main:app --reload   # terminal 1, puerto 8000
cd frontend && npm install && npm run dev     # terminal 2, puerto 5173
```

Abrir `http://localhost:5173`. El backend tiene CORS habilitado para ese
origen (ver `backend/app/main.py`).

Si el backend corre en otro host/puerto, crear un archivo `.env.local` en
esta carpeta (no se versiona) con:

```
VITE_API_BASE_URL=http://tu-host:puerto
```

## Estructura

- `src/api.ts` -- todas las llamadas HTTP al backend.
- `src/tabla.ts` -- el UNICO componente de tabla (busqueda libre + recorte a
  1.000 filas + "Cargar la tabla completa"), igual que `_mostrar_tabla_estandar`
  en la UI de Streamlit. No crear un segundo mecanismo de tabla.
- `src/salud.ts` -- el banner de "datos desactualizados/error", consulta
  `/salud` cada minuto.
- `src/tarjetas.ts` -- tarjetas de metrica compactas con tooltip nativo.
- `src/vista-candidatos.ts` / `src/vista-auditoria.ts` -- las dos pantallas.

## Build de produccion

```bash
npm run build   # genera frontend/dist/, servible como estatico
```
