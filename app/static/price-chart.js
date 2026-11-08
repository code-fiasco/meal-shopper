(function () {
  var canvas = document.getElementById("price-chart");
  var dataNode = document.getElementById("price-data");
  if (!canvas || !dataNode || typeof Chart === "undefined") {
    return;
  }
  var payload = JSON.parse(dataNode.textContent);
  new Chart(canvas, {
    type: "line",
    data: {
      labels: payload.labels,
      datasets: [
        {
          label: "Pack price",
          data: payload.pence.map(function (pence) {
            return pence / 100;
          }),
          borderColor: "#14352a",
          backgroundColor: "#14352a",
          tension: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom" } },
      scales: {
        y: {
          ticks: {
            callback: function (value) {
              return "£" + Number(value).toFixed(2);
            },
          },
        },
      },
    },
  });
})();
