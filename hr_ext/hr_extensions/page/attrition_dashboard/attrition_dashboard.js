frappe.pages["attrition_dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Attrition Dashboard",
		single_column: true,
	});
	let page = wrapper.page;
	page.add_action("Recompute", function () {
		load(true);
	});

	buildSummaryShell();
	load(false);

	function buildSummaryShell() {
		let cards = [
			["low", "LOW RISK"],
			["medium", "MEDIUM RISK"],
			["high", "HIGH RISK"],
			["total", "TOTAL SCORED"],
		];
		cards.forEach(function (c) {
			$(
				'<div class="col-sm-3" style="padding:6px">' +
					'<div class="frappe-card text-center" style="padding:18px">' +
					'<div class="h4 mb-1" id="attrition-kpi-' + c[0] + '">-</div>' +
					'<div class="text-muted small">' + c[1] + "</div></div></div>"
			).appendTo("#attrition-summary");
		});
	}

	function load(recompute) {
		frappe.call({
			method: "hr_ext.api.attrition.overview",
			args: { recompute: recompute },
			callback: function (r) {
				render(r.message || {});
			},
		});
	}

	function render(data) {
		let s = data.summary || {};
		["low", "medium", "high", "total"].forEach(function (k) {
			$("#attrition-kpi-" + k).text(s[k] || 0);
		});
		if (data.hint) {
			$("#attrition-hint").text(data.hint).show();
		} else {
			$("#attrition-hint").hide();
		}

		let rows = data.rows || [];
		let $table = $(
			'<table class="table table-hover"><thead><tr><th>Employee</th><th>Score</th><th>Level</th><th>Scored On</th></tr></thead><tbody></tbody></table>'
		);
		rows.forEach(function (r) {
			let $tr = $("<tr></tr>");
			$("<td></td>").text(r.employee_name || r.employee).appendTo($tr);
			$("<td></td>").text(r.score).appendTo($tr);
			$("<td></td>").text(r.risk_level).appendTo($tr);
			$("<td></td>").text(r.scored_on).appendTo($tr);
			$tr.appendTo($table.find("tbody"));
		});
		$("#attrition-list").empty().append($table);
	}
};