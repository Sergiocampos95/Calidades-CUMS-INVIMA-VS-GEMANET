import { montarBannerSalud } from "./salud";
import { montarVistaAuditoria } from "./vista-auditoria";
import { montarVistaCandidatos } from "./vista-candidatos";

type NombreVista = "candidatos" | "auditoria";

const MONTADORES: Record<NombreVista, (contenedor: HTMLElement) => Promise<void>> = {
  candidatos: montarVistaCandidatos,
  auditoria: montarVistaAuditoria,
};

function inicializarNavegacion(): void {
  const contenido = document.getElementById("contenido");
  const botones = document.querySelectorAll<HTMLButtonElement>("#navegacion .boton-nav");
  if (!contenido) return;

  const activar = (vista: NombreVista) => {
    for (const boton of botones) {
      boton.classList.toggle("boton-nav--activo", boton.dataset.vista === vista);
    }
    void MONTADORES[vista](contenido);
  };

  for (const boton of botones) {
    boton.addEventListener("click", () => activar(boton.dataset.vista as NombreVista));
  }

  activar("candidatos");
}

const bannerSalud = document.getElementById("banner-salud");
if (bannerSalud) montarBannerSalud(bannerSalud);

inicializarNavegacion();
