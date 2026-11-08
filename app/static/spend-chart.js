(function () {
  var canvas = document.getElementById("spend-chart");
  var dataNode = document.getElementById("spend-data");
  if (!canvas || !dataNode || typeof Chart === "undefined") {
    return;
  }
  var payload = JSON.parse(dataNode.textContent);
  function pounds(pence) {
    if (pence === null || pence === undefined) {
      return null;
    }
    return pence / 100;
  }
  var hatch = document.createElement("canvas");
  hatch.width = 8;
  hatch.height = 8;
  var pen = hatch.getContext("2d");
  pen.strokeStyle = "#14352a";
  pen.lineWidth = 2;
  pen.beginPath();
  pen.moveTo(0, 8);
  pen.lineTo(8, 0);
  pen.stroke();
  var pattern = canvas.getContext("2d").createPattern(hatch, "repeat");
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: payload.labels,
      datasets: [
        {
          label: "Grocery (actual)",
          data: payload.grocery.map(pounds),
          backgroundColor: "#14352a",
          stack: "spent",
        },
        {
          label: "Takeaway",
          data: payload.takeaway.map(pounds),
          backgroundColor: "#9a3412",
          stack: "spent",
        },
        {
          label: "Estimated outlay",
          data: payload.estimated.map(pounds),
          backgroundColor: pattern,
          borderColor: "#14352a",
          borderWidth: 2,
          stack: "estimate",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: {
            label: function (item) {
              var name = item.dataset.label;
              if (item.raw === null && name === "Grocery (actual)") {
                return name + ": Unrecorded";
              }
              if (item.raw === null) {
                return name + ": none";
              }
              return name + ": £" + Number(item.raw).toFixed(2);
            },
          },
        },
      },
      scales: {
        x: { stacked: true },
        y: {
          stacked: true,
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
