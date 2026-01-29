let currentId = null;
let currentData = null;
let previewTimeout = null;

const el = (id) => document.getElementById(id);
const status = (msg) => el("status").textContent = msg || "";

function emptyCardData() {
  return {
    piece_number: "",
    piece_type: "other",
    cabinet_number: "",
    name_query: "",
    title: "",
    year: "",
    subtitle: "",
    bullets: ["", "", "", ""],
    tech: [
      {label:"", value:""},
      {label:"", value:""},
      {label:"", value:""},
      {label:"", value:""},
    ],
    notes: "",
    image_path: null,
    render_path: null
  };
}

function renderBulletsUI(bullets) {
  const root = el("bullets");
  root.innerHTML = "";
  bullets.forEach((b, i) => {
    const row = document.createElement("div");
    row.className = "fieldline";
    const inp = document.createElement("input");
    inp.value = b;
    inp.placeholder = `Bullet ${i+1}`;
    inp.oninput = () => { 
      currentData.bullets[i] = inp.value;
      updatePreview();
    };
    const del = document.createElement("button");
    del.className = "smallbtn";
    del.textContent = "🗑";
    del.onclick = () => {
      currentData.bullets.splice(i,1);
      renderBulletsUI(currentData.bullets);
      updatePreview();
    };
    row.appendChild(inp);
    row.appendChild(del);
    root.appendChild(row);
  });
}

function renderTechUI(tech) {
  const root = el("tech");
  root.innerHTML = "";
  tech.forEach((t, i) => {
    const row = document.createElement("div");
    row.className = "fieldline";
    const inpL = document.createElement("input");
    inpL.className = "mini";
    inpL.value = t.label || "";
    inpL.placeholder = "Etiqueta";
    inpL.oninput = () => { 
      currentData.tech[i].label = inpL.value;
      updatePreview();
    };

    const inpV = document.createElement("input");
    inpV.value = t.value || "";
    inpV.placeholder = "Valor";
    inpV.oninput = () => { 
      currentData.tech[i].value = inpV.value;
      updatePreview();
    };

    const del = document.createElement("button");
    del.className = "smallbtn";
    del.textContent = "🗑";
    del.onclick = () => {
      currentData.tech.splice(i,1);
      renderTechUI(currentData.tech);
      updatePreview();
    };

    row.appendChild(inpL);
    row.appendChild(inpV);
    row.appendChild(del);
    root.appendChild(row);
  });
}

function syncFormFromData() {
  el("piece_number").value = currentData.piece_number || "";
  el("cabinet_number").value = currentData.cabinet_number || "";
  el("piece_type").value = currentData.piece_type || "other";
  el("name_query").value = currentData.name_query || "";
  el("title").value = currentData.title || "";
  el("year").value = currentData.year || "";
  el("subtitle").value = currentData.subtitle || "";
  el("image_url").value = currentData.image_path || "";
  renderBulletsUI(currentData.bullets || []);
  renderTechUI(currentData.tech || []);
  updatePreview();
}

function syncDataFromForm() {
  currentData.piece_number = el("piece_number").value.trim();
  currentData.cabinet_number = el("cabinet_number").value.trim();
  currentData.piece_type = el("piece_type").value;
  currentData.name_query = el("name_query").value.trim();
  currentData.title = el("title").value;
  currentData.year = el("year").value;
  currentData.subtitle = el("subtitle").value;
  currentData.image_path = el("image_url").value.trim() || null;
  // bullets + tech ya se actualizan por oninput
  updatePreview();
}

async function updatePreview() {
  // Cancelar timeout anterior
  if (previewTimeout) {
    clearTimeout(previewTimeout);
  }
  
  // Debounce de 500ms para no hacer demasiadas peticiones
  previewTimeout = setTimeout(async () => {
    if (!currentData) {
      el("previewImg").src = "";
      return;
    }
    
    try {
      const response = await api("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          data: currentData,
          dither: parseInt(el("dither").value, 10)
        }),
      });
      
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      el("previewImg").src = url;
    } catch (e) {
      console.error("Error al actualizar preview:", e);
      // No mostrar error en status para no molestar durante edición
    }
  }, 500);
}

async function loadCardsList(q = "", piece_type = "") {
  try {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (piece_type && piece_type !== "all") params.set("piece_type", piece_type);
    
    const response = await api(`/api/cards?${params}`);
    const cards = await response.json();
    
    const listEl = el("list");
    listEl.innerHTML = "";
    
    cards.forEach(card => {
      const row = document.createElement("div");
      row.className = "cardrow";
      const cabinetDisplay = card.cabinet_number ? `Vitrina ${card.cabinet_number} · ` : "";
      row.innerHTML = `
        <div>
          <div class="title">${card.title || "Sin título"}</div>
          <div class="meta">${cabinetDisplay}${card.piece_number || ""} · ${card.piece_type || ""}</div>
        </div>
        <div class="actions">
          <button class="smallbtn" onclick="loadCard('${card.id}')">Editar</button>
        </div>
      `;
      listEl.appendChild(row);
    });
  } catch (e) {
    console.error("Error al cargar lista:", e);
  }
}

async function loadCard(id) {
  try {
    const response = await api(`/api/cards/${id}`);
    const rec = await response.json();
    currentId = rec.id;
    currentData = rec.data;
    syncFormFromData();
    status(`Cargada: ${currentId}`);
  } catch (e) {
    status(`Error al cargar: ${e.message}`);
  }
}

async function api(path, opts={}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r;
}

document.addEventListener("DOMContentLoaded", () => {
  // Botón hamburguesa para plegar/desplegar listado
  el("toggleList").onclick = () => {
    el("listPanel").classList.toggle("collapsed");
  };

  // Búsqueda y filtros
  el("search").oninput = () => {
    loadCardsList(el("search").value, el("typeFilter").value);
  };
  el("typeFilter").onchange = () => {
    loadCardsList(el("search").value, el("typeFilter").value);
  };
  el("refreshBtn").onclick = () => {
    loadCardsList(el("search").value, el("typeFilter").value);
  };

  // Listeners en tiempo real para actualizar preview
  ["piece_number", "cabinet_number", "piece_type", "name_query", "title", "year", "subtitle", "image_url"].forEach(id => {
    el(id).oninput = () => syncDataFromForm();
  });
  
  // Listener para dithering
  el("dither").onchange = () => updatePreview();

  // Botón: Nueva cartela
  el("newBtn").onclick = () => {
    currentId = null;
    currentData = emptyCardData();
    syncFormFromData();
    el("previewImg").src = "";
    status("Nueva cartela creada");
  };

  // Botón: Generar sugerencia
  el("suggestBtn").onclick = async () => {
    if (!currentData) currentData = emptyCardData();
    syncDataFromForm();
    const name_query = currentData.name_query.trim();
    if (!name_query) {
      status("Por favor, ingresa un nombre o consulta");
      return;
    }

    status("Generando sugerencia...");
    try {
      const response = await api("/api/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name_query: currentData.name_query,
          piece_type: currentData.piece_type,
          piece_number: currentData.piece_number,
        }),
      });
      const suggestion = await response.json();
      
      // Actualizar los datos con la sugerencia
      if (suggestion.title) currentData.title = suggestion.title;
      if (suggestion.subtitle) currentData.subtitle = suggestion.subtitle;
      if (suggestion.bullets && suggestion.bullets.length > 0) {
        currentData.bullets = suggestion.bullets;
      }
      if (suggestion.tech && suggestion.tech.length > 0) {
        currentData.tech = suggestion.tech;
      }
      
      // Actualizar la UI
      syncFormFromData();
      status("Sugerencia cargada!");
    } catch (e) {
      status(`Error: ${e.message}`);
    }
  };

  // Botón: Guardar
  el("saveBtn").onclick = async () => {
    if (!currentData) {
      status("No hay datos para guardar");
      return;
    }

    syncDataFromForm();
    status("Guardando...");
    
    try {
      let response;
      if (currentId) {
        // Actualizar cartela existente
        response = await api(`/api/cards/${currentId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: currentData }),
        });
      } else {
        // Crear nueva cartela
        response = await api("/api/cards", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: currentData }),
        });
      }
      
      const saved = await response.json();
      currentId = saved.id;
      currentData = saved.data;
      status(`Guardado! ID: ${currentId}`);
      
      // Actualizar listado
      loadCardsList(el("search").value, el("typeFilter").value);
    } catch (e) {
      status(`Error al guardar: ${e.message}`);
    }
  };

  // Botón: Renderizar + Descargar PNG
  el("renderBtn").onclick = async () => {
    if (!currentId) {
      status("Debes guardar la cartela primero");
      return;
    }

    syncDataFromForm();
    status("Renderizando...");

    try {
      const formData = new FormData();
      formData.append("data", JSON.stringify(currentData));
      formData.append("dither", el("dither").value);

      const response = await fetch(`/api/cards/${currentId}/render`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) throw new Error(await response.text());

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      
      // Actualizar preview
      el("previewImg").src = url;
      
      // Descargar automáticamente
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentId}.png`;
      a.click();
      
      status("Renderizado y descargado!");
    } catch (e) {
      status(`Error al renderizar: ${e.message}`);
    }
  };

  // Botón: Renderizar y descargar como TRI
  el("renderTriBtn").onclick = async () => {
    if (!currentId) {
      status("Debes guardar la cartela primero");
      return;
    }

    syncDataFromForm();
    status("Generando TRI...");

    try {
      const response = await fetch(`/api/cards/${currentId}/render.tri`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dither: parseInt(el("dither").value, 10)
        }),
      });

      if (!response.ok) throw new Error(await response.text());

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      
      // Descargar automáticamente
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentId}.tri`;
      a.click();
      
      status("TRI descargado!");
    } catch (e) {
      status(`Error al generar TRI: ${e.message}`);
    }
  };

  // Botón: Duplicar
  el("duplicateBtn").onclick = async () => {
    if (!currentId) {
      status("Selecciona una cartela para duplicar");
      return;
    }

    status("Duplicando...");
    try {
      const response = await api(`/api/cards/${currentId}/duplicate`, {
        method: "POST",
      });
      
      const duplicated = await response.json();
      currentId = duplicated.id;
      currentData = duplicated.data;
      syncFormFromData();
      status(`Duplicado! Nuevo ID: ${currentId}`);
    } catch (e) {
      status(`Error al duplicar: ${e.message}`);
    }
  };

  // Botón: Añadir bullet
  el("addBulletBtn").onclick = () => {
    if (!currentData) currentData = emptyCardData();
    currentData.bullets.push("");
    renderBulletsUI(currentData.bullets);
  };

  // Botón: Añadir línea técnica
  el("addTechBtn").onclick = () => {
    if (!currentData) currentData = emptyCardData();
    currentData.tech.push({ label: "", value: "" });
    renderTechUI(currentData.tech);
  };

  // Inicializar con cartela vacía y cargar listado
  currentData = emptyCardData();
  syncFormFromData();
  loadCardsList();
});