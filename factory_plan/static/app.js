async function loadJson(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

function renderRows(tableBody, rows, columns) {
    tableBody.innerHTML = "";

    if (!rows.length) {
        const empty = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = columns.length;
        cell.className = "empty-state";
        cell.textContent = "Даних поки немає";
        empty.appendChild(cell);
        tableBody.appendChild(empty);
        return;
    }

    for (const row of rows) {
        const tr = document.createElement("tr");
        for (const column of columns) {
            const td = document.createElement("td");
            td.textContent = row[column] ?? "";
            tr.appendChild(td);
        }
        tableBody.appendChild(tr);
    }
}

window.FactoryPlan = {
    loadJson,
    renderRows,
};

