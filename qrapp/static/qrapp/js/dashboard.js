// Dashboard JavaScript
class Dashboard {
    constructor() {
        this.currentSection = 'dashboard';
        this.filters = {
            year: '',
            college: '',
            program: '',
            status: '',
            search: '',
            date: '',
            startDate: '',
            endDate: '',
            startTime: '',
            endTime: ''
        };
        // Pagination settings
        this.pagination = {
            dashboard: { currentPage: 1, rowsPerPage: 10 },
            students: { currentPage: 1, rowsPerPage: 10 },
            reports: { currentPage: 1, rowsPerPage: 10 }
        };
        this.init();
    }

    init() {
        this.initEventListeners();
        this.initKeyboardShortcuts();
        this.loadInitialData();
    }

    initEventListeners() {
        // Per-menu filter changes
        document.querySelectorAll('.filter-section .filter-control').forEach(control => {
            if (control.classList.contains('filter-search') || control.dataset.filter === 'search') {
                control.addEventListener('input', this.debounce(() => this.applyFilters(), 500));
            } else {
                control.addEventListener('change', () => this.applyFilters());
            }
        });

        // Clear only the active menu's filters
        document.querySelectorAll('.clear-filters-btn').forEach(btn => {
            btn.addEventListener('click', () => this.clearFilters());
        });

        // Export buttons
        document.querySelectorAll('[data-export]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tableId = e.currentTarget.dataset.export;
                this.exportToCSV(tableId);
            });
        });

        // Print button
        const printBtn = document.getElementById('printBtn');
        if (printBtn) {
            printBtn.addEventListener('click', () => window.print());
        }
    }

    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + F for search in active menu
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                e.preventDefault();
                this.getActiveFilterSection()
                    ?.querySelector('[data-filter="search"]')
                    ?.focus();
            }

            // Escape to clear active menu filters
            if (e.key === 'Escape') {
                this.clearFilters();
            }
        });
    }

    getActiveFilterSection() {
        return document.querySelector(`.filter-section[data-for="${this.currentSection}"]`);
    }

    showSection(sectionId, element) {
        // Hide all sections
        document.querySelectorAll('.tabs').forEach(tab => {
            tab.classList.remove('active');
        });

        // Show selected section
        const section = document.getElementById(sectionId);
        if (section) {
            section.classList.add('active');
        }

        // Update nav
        document.querySelectorAll('.sidebar-nav a').forEach(link => {
            link.classList.remove('active');
        });
        if (element) {
            element.classList.add('active');
        }

        // Switch stats based on active section
        this.switchStats(sectionId);

        this.currentSection = sectionId;
        this.applyFilters();

        if (document.getElementById(sectionId) && history.replaceState) {
            history.replaceState(null, '', '#' + sectionId);
        }
    }

    switchStats(sectionId) {
        const globalStats = document.getElementById('globalStats');
        if (globalStats) {
            globalStats.style.display = sectionId === 'dashboard' ? 'block' : 'none';
        }
    }

    updateStats(stats) {
        if (!stats) return;

        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value ?? 0;
        };

        setText('expectedCount', stats.expected);
        setText('attendedCount', stats.attended);
        setText('absentCount', stats.absent);
        setText('presentInCount', stats.still_inside ?? stats.present_in);
        setText('presentOutCount', stats.completed ?? stats.present_out);
        setText('totalScansCount', stats.total_scans);
        setText('attendanceRate', `${stats.attendance_rate ?? 0}%`);
        setText('completionRate', `${stats.completion_rate ?? 0}%`);
        setText('firstCheckin', stats.first_checkin || '-');
        setText('lastActivity', stats.last_activity || '-');
        setText('peakHour', stats.peak_hour || '-');

        const peakHint = document.getElementById('peakHourCount');
        if (peakHint) {
            peakHint.textContent = stats.peak_hour_count
                ? `${stats.peak_hour_count} check-ins`
                : 'No check-ins yet';
        }

        const scansCard = document.getElementById('totalScansCount')?.closest('.stat-card');
        const scansHint = scansCard?.querySelector('.stat-hint');
        if (scansHint) {
            scansHint.textContent = `${stats.total_in_scans || 0} IN · ${stats.total_out_scans || 0} OUT`;
        }

        this.renderBreakdown('collegeBreakdown', stats.college_breakdown || []);
        this.renderBreakdown('yearBreakdown', stats.year_breakdown || []);
        this.renderSexBreakdown(stats.sex_breakdown || []);
    }

    renderBreakdown(containerId, rows) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!rows.length) {
            container.innerHTML = '<p class="breakdown-empty">No attendance data yet</p>';
            return;
        }

        container.innerHTML = rows.map(row => `
            <div class="breakdown-row">
                <div class="breakdown-top">
                    <span>${this.escapeHtml(String(row.label))}</span>
                    <span>${row.count} <small>(${row.percent}%)</small></span>
                </div>
                <div class="breakdown-bar"><span style="width: ${row.bar || 0}%;"></span></div>
            </div>
        `).join('');
    }

    renderSexBreakdown(rows) {
        const container = document.getElementById('sexBreakdown');
        if (!container) return;

        if (!rows.length) {
            container.innerHTML = '<p class="breakdown-empty">No attendance data yet</p>';
            return;
        }

        container.innerHTML = rows.map(row => `
            <div class="sex-chip">
                <strong>${row.count}</strong>
                <span>${this.escapeHtml(String(row.label))}</span>
                <small>${row.percent}%</small>
            </div>
        `).join('');
    }

    applyFilters() {
        // Reset, then collect only the active menu's filter values
        Object.keys(this.filters).forEach(key => {
            this.filters[key] = '';
        });

        const filterSection = this.getActiveFilterSection();
        if (filterSection) {
            filterSection.querySelectorAll('[data-filter]').forEach(control => {
                const key = control.dataset.filter;
                if (key && Object.prototype.hasOwnProperty.call(this.filters, key)) {
                    this.filters[key] = control.value || '';
                }
            });
        }

        // Build query params (map camelCase UI keys to API snake_case)
        const paramMap = {
            year: 'year',
            college: 'college',
            program: 'program',
            status: 'status',
            search: 'search',
            date: 'date',
            startDate: 'start_date',
            endDate: 'end_date',
            startTime: 'start_time',
            endTime: 'end_time'
        };

        const params = new URLSearchParams();
        Object.keys(this.filters).forEach(key => {
            if (this.filters[key] && paramMap[key]) {
                params.append(paramMap[key], this.filters[key]);
            }
        });

        // Load data based on current section
        this.loadData(params);
    }

    async loadData(params) {
        let endpoint = '';
        
        switch (this.currentSection) {
            case 'students':
                endpoint = '/ajax/student-list/';
                break;
            case 'dashboard':
                endpoint = '/ajax/dashboard-data/';
                break;
            case 'reports':
                endpoint = '/ajax/reports-data/';
                break;
            default:
                return;
        }

        try {
            this.showLoading();
            const response = await fetch(`${endpoint}?${params}`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) throw new Error('Network error');

            const data = await response.json();
            
            if (data.success) {
                this.updateUI(data);
            } else {
                this.showError('Failed to load data');
            }
        } catch (error) {
            console.error('Error loading data:', error);
            this.showError('Failed to load data');
        }
    }

    updateUI(data) {
        switch (this.currentSection) {
            case 'students':
                this.updateStudentsTable(data.students);
                break;
            case 'dashboard':
                this.updateDashboardTable(data.records);
                break;
            case 'reports':
                this.updateReportsTable(data.reports);
                break;
        }

        if (data.stats) {
            this.updateStats(data.stats);
        }
    }

    updateStudentsTable(students) {
        const tbody = document.getElementById('studentsTableBody');
        if (!tbody) return;

        if (!students || students.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">No students found</td></tr>';
            this.updatePaginationControls('students', 1, 1, 0);
            return;
        }

        tbody.innerHTML = students.map(student => `
            <tr>
                <td>${this.escapeHtml(student.student_id)}</td>
                <td>${this.escapeHtml(student.name)}</td>
                <td>${this.escapeHtml(student.college)}</td>
                <td>${this.escapeHtml(student.program)}</td>
                <td>${student.year}</td>
                <td>${this.escapeHtml(student.major)}</td>
                <td>
                    <a href="/edit_student/${student.id}/" class="btn btn-warning btn-sm">
                        <i class="fas fa-edit"></i> Edit
                    </a>
                    <a href="/delete_student/${student.id}/" class="btn btn-danger btn-sm" 
                       onclick="return confirm('Delete this student?');">
                        <i class="fas fa-trash"></i> Delete
                    </a>
                </td>
            </tr>
        `).join('');

        // Apply pagination
        this.resetPagination('students');
        this.paginateTable('studentsTable', 'students');
    }

    updateDashboardTable(records) {
        const tbody = document.getElementById('dashboardTableBody');
        if (!tbody) return;

        if (!records || records.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center">No records found</td></tr>';
            this.updatePaginationControls('dashboard', 1, 1, 0);
            return;
        }

        tbody.innerHTML = records.map(record => `
            <tr>
                <td>${this.escapeHtml(record.student_id)}</td>
                <td>${this.escapeHtml(record.name)}</td>
                <td>${this.escapeHtml(record.college)}</td>
                <td>${this.escapeHtml(record.program)}</td>
                <td>${record.year}</td>
                <td>${this.escapeHtml(record.major)}</td>
                <td><span class="badge badge-${this.getStatusClass(record.status)}">${record.status}</span></td>
                <td>${record.date || '-'}</td>
                <td>${record.timestamp || '-'}</td>
            </tr>
        `).join('');

        // Apply pagination
        this.resetPagination('dashboard');
        this.paginateTable('dashboardTable', 'dashboard');
    }

    updateReportsTable(reports) {
        const tbody = document.getElementById('reportsTableBody');
        if (!tbody) return;

        if (!reports || reports.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center">No reports found</td></tr>';
            this.updatePaginationControls('reports', 1, 1, 0);
            return;
        }

        tbody.innerHTML = reports.map(report => `
            <tr>
                <td>${this.escapeHtml(report.student_id)}</td>
                <td>${this.escapeHtml(report.name)}</td>
                <td>${this.escapeHtml(report.college)}</td>
                <td>${this.escapeHtml(report.program)}</td>
                <td>${report.year}</td>
                <td>${this.escapeHtml(report.major)}</td>
                <td>${report.time_in || '-'}</td>
                <td>${report.time_out || '-'}</td>
                <td>${report.date || '-'}</td>
                <td><span class="badge badge-${this.getStatusClass(report.status)}">${report.status}</span></td>
            </tr>
        `).join('');

        // Apply pagination
        this.resetPagination('reports');
        this.paginateTable('reportsTable', 'reports');
    }

    clearFilters() {
        const filterSection = this.getActiveFilterSection();
        if (!filterSection) return;

        filterSection.querySelectorAll('.filter-control').forEach(control => {
            if (control.type === 'checkbox') {
                control.checked = false;
            } else {
                control.value = '';
            }
        });
        this.applyFilters();
    }

    showLoading() {
        const tables = ['studentsTableBody', 'dashboardTableBody', 'reportsTableBody'];
        tables.forEach(id => {
            const tbody = document.getElementById(id);
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="10" class="text-center">Loading...</td></tr>';
            }
        });
    }

    showError(message) {
        const tables = ['studentsTableBody', 'dashboardTableBody', 'reportsTableBody'];
        tables.forEach(id => {
            const tbody = document.getElementById(id);
            if (tbody && tbody.textContent.includes('Loading')) {
                tbody.innerHTML = `<tr><td colspan="10" class="text-center" style="color: var(--danger);">${message}</td></tr>`;
            }
        });
    }

    exportToCSV(tableId) {
        const table = document.getElementById(tableId);
        if (!table) return;

        let csv = [];
        const rows = table.querySelectorAll('tr');

        rows.forEach(row => {
            const cols = row.querySelectorAll('td, th');
            const rowData = Array.from(cols).map(col => {
                let text = col.textContent.trim().replace(/\s+/g, ' ');
                return `"${text}"`;
            });
            csv.push(rowData.join(','));
        });

        const csvContent = csv.join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);

        link.setAttribute('href', url);
        link.setAttribute('download', `${tableId}_${Date.now()}.csv`);
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    loadInitialData() {
        // Apply pagination to initial data
        setTimeout(() => {
            this.paginateTable('dashboardTable', 'dashboard');
            this.paginateTable('studentsTable', 'students');
            this.paginateTable('reportsTable', 'reports');
        }, 100);
    }

    getStatusClass(status) {
        const statusMap = {
            'ABSENT': 'danger',
            'PRESENT': 'success',
            'IN': 'info',
            'OUT': 'warning',
            'COMPLETED': 'success'
        };
        return statusMap[status?.toUpperCase()] || 'info';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Pagination methods
    paginateTable(tableId, section) {
        const table = document.getElementById(tableId);
        if (!table) return;

        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr')).filter(row => 
            row.style.display !== 'none' && row.cells.length > 1
        );

        const { currentPage, rowsPerPage } = this.pagination[section];
        const totalPages = Math.ceil(rows.length / rowsPerPage);
        const start = (currentPage - 1) * rowsPerPage;
        const end = start + rowsPerPage;

        // Hide all rows first
        tbody.querySelectorAll('tr').forEach(row => {
            if (row.cells.length > 1) {
                row.classList.add('pagination-hidden');
            }
        });

        // Show only current page rows
        rows.slice(start, end).forEach(row => {
            row.classList.remove('pagination-hidden');
        });

        // Update pagination controls
        this.updatePaginationControls(section, currentPage, totalPages, rows.length);
    }

    updatePaginationControls(section, currentPage, totalPages, totalRows) {
        const paginationId = `${section}Pagination`;
        const paginationEl = document.getElementById(paginationId);
        
        if (!paginationEl) return;

        const start = totalRows === 0 ? 0 : ((currentPage - 1) * this.pagination[section].rowsPerPage) + 1;
        const end = Math.min(currentPage * this.pagination[section].rowsPerPage, totalRows);

        paginationEl.innerHTML = `
            <div class="pagination-info">
                Showing ${start}-${end} of ${totalRows} records
            </div>
            <div class="pagination-controls">
                <button class="btn btn-sm" ${currentPage === 1 ? 'disabled' : ''} 
                        onclick="dashboard.changePage('${section}', ${currentPage - 1})">
                    <i class="fas fa-chevron-left"></i> Previous
                </button>
                <span class="pagination-page">Page ${currentPage} of ${totalPages || 1}</span>
                <button class="btn btn-sm" ${currentPage >= totalPages ? 'disabled' : ''} 
                        onclick="dashboard.changePage('${section}', ${currentPage + 1})">
                    Next <i class="fas fa-chevron-right"></i>
                </button>
            </div>
        `;
    }

    changePage(section, newPage) {
        this.pagination[section].currentPage = newPage;
        
        const tableMap = {
            'dashboard': 'dashboardTable',
            'students': 'studentsTable',
            'reports': 'reportsTable'
        };

        this.paginateTable(tableMap[section], section);
    }

    resetPagination(section) {
        this.pagination[section].currentPage = 1;
    }
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
    initSidebarToggle();

    const hash = (window.location.hash || '').replace('#', '');
    if (hash && document.getElementById(hash)) {
        const link = document.querySelector(`.sidebar-nav a[data-section="${hash}"]`);
        window.dashboard.showSection(hash, link);
    }
});

function initSidebarToggle() {
    const STORAGE_KEY = 'qr_sidebar_collapsed';
    const toggleBtn = document.getElementById('sidebarToggle');
    const openBtn = document.getElementById('sidebarOpenBtn');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (!toggleBtn && !openBtn) return;

    const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

    const setCollapsed = (collapsed, persist = true) => {
        document.body.classList.toggle('sidebar-collapsed', collapsed);
        // When the sidebar is open on mobile, lock body scrolling so the
        // background doesn't scroll/bleed under the backdrop.
        document.body.classList.toggle('sidebar-open', !collapsed && isMobile());
        if (backdrop) {
            if (collapsed) {
                backdrop.setAttribute('hidden', '');
            } else {
                backdrop.removeAttribute('hidden');
            }
        }
        if (persist && !isMobile()) {
            localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        }
    };

    const toggle = () => {
        setCollapsed(!document.body.classList.contains('sidebar-collapsed'));
    };

    // Mobile starts collapsed; desktop restores saved preference
    if (isMobile()) {
        setCollapsed(true, false);
    } else {
        setCollapsed(localStorage.getItem(STORAGE_KEY) === '1', false);
    }

    toggleBtn?.addEventListener('click', toggle);
    openBtn?.addEventListener('click', () => setCollapsed(false));
    backdrop?.addEventListener('click', () => setCollapsed(true, !isMobile()));

    window.addEventListener('resize', () => {
        if (isMobile()) {
            setCollapsed(true, false);
        } else {
            setCollapsed(localStorage.getItem(STORAGE_KEY) === '1', false);
        }
    });
}

// Used by sidebar: switch tabs on admin dashboard, otherwise navigate there.
function navigateDashboardSection(link) {
    const sectionId = link.dataset.section;
    if (!sectionId) return true;

    if (typeof window.dashboard !== 'undefined' && document.getElementById(sectionId)) {
        window.dashboard.showSection(sectionId, link);
        // On mobile, close sidebar after navigating a section
        if (window.matchMedia('(max-width: 768px)').matches) {
            document.body.classList.add('sidebar-collapsed');
        }
        return false;
    }
    return true;
}

// Modal functions
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
    }
}

// Close modal on outside click
window.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        e.target.classList.remove('active');
    }
});

// Print Options Handler
function applyPrintOptions() {
    // Collect filter values
    const filters = {
        event: document.getElementById('printEvent')?.value || '',
        college: document.getElementById('printCollege')?.value || '',
        program: document.getElementById('printProgram')?.value || '',
        dateFrom: document.getElementById('printDateFrom')?.value || '',
        dateTo: document.getElementById('printDateTo')?.value || '',
        timeFrom: document.getElementById('printTimeFrom')?.value || '',
        timeTo: document.getElementById('printTimeTo')?.value || '',
        gender: document.getElementById('printGender')?.value || '',
        includeHeaders: document.getElementById('printIncludeHeaders')?.checked,
        includeStats: document.getElementById('printIncludeStats')?.checked
    };

    // Get filtered table data
    const table = document.getElementById('reportsTable');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr')).filter(row => 
        !row.classList.contains('pagination-hidden') && row.cells.length > 1
    );

    // Filter rows based on criteria
    let filteredRows = rows.filter(row => {
        const cells = row.cells;
        let matches = true;

        // College filter
        if (filters.college && cells[2]?.textContent.trim() !== filters.college) {
            matches = false;
        }

        // Program filter
        if (filters.program && cells[3]?.textContent.trim() !== filters.program) {
            matches = false;
        }

        // Gender filter (need to check student data - for now skip)
        // Date filtering would need proper date parsing from cells[8]

        return matches;
    });

    // Create print window
    const printWindow = window.open('', '_blank', 'width=800,height=600');
    
    let printContent = '<html><head><title>Attendance Report</title>';
    printContent += '<style>';
    printContent += 'body { font-family: Arial, sans-serif; padding: 20px; }';
    printContent += 'h1, h2 { color: #4361ee; }';
    printContent += 'table { width: 100%; border-collapse: collapse; margin: 20px 0; }';
    printContent += 'th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 12px; }';
    printContent += 'th { background-color: #4361ee; color: white; }';
    printContent += 'tr:nth-child(even) { background-color: #f2f2f2; }';
    printContent += '.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin: 20px 0; }';
    printContent += '.stat-box { padding: 15px; background: #f5f7fa; border-radius: 8px; }';
    printContent += '.stat-label { font-size: 12px; color: #6b7280; text-transform: uppercase; }';
    printContent += '.stat-value { font-size: 24px; font-weight: bold; color: #1f2937; }';
    printContent += '@media print { button { display: none; } }';
    printContent += '</style></head><body>';

    // Add header if enabled
    if (filters.includeHeaders) {
        printContent += '<h1>QR Attendance System</h1>';
        printContent += '<h2>Attendance Report</h2>';
        if (filters.event) {
            printContent += `<p><strong>Event:</strong> ${filters.event}</p>`;
        }
        printContent += `<p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>`;
        if (filters.dateFrom || filters.dateTo) {
            printContent += '<p><strong>Date Range:</strong> ';
            printContent += filters.dateFrom ? `From ${filters.dateFrom}` : '';
            printContent += filters.dateTo ? ` To ${filters.dateTo}` : '';
            printContent += '</p>';
        }
        printContent += '<hr>';
    }

    // Add statistics if enabled
    if (filters.includeStats) {
        const totalRecords = filteredRows.length;
        const completedRecords = filteredRows.filter(row => 
            row.cells[9]?.textContent.includes('COMPLETED')
        ).length;
        const pendingRecords = filteredRows.filter(row => 
            row.cells[9]?.textContent.includes('IN') || row.cells[9]?.textContent.includes('PRESENT')
        ).length;

        printContent += '<div class="stats">';
        printContent += '<div class="stat-box">';
        printContent += '<div class="stat-label">Total Records</div>';
        printContent += `<div class="stat-value">${totalRecords}</div>`;
        printContent += '</div>';
        printContent += '<div class="stat-box">';
        printContent += '<div class="stat-label">Completed</div>';
        printContent += `<div class="stat-value">${completedRecords}</div>`;
        printContent += '</div>';
        printContent += '<div class="stat-box">';
        printContent += '<div class="stat-label">Pending</div>';
        printContent += `<div class="stat-value">${pendingRecords}</div>`;
        printContent += '</div>';
        printContent += '</div>';
    }

    // Add filtered table
    printContent += '<table>';
    printContent += '<thead><tr>';
    printContent += '<th>ID</th><th>Name</th><th>College</th><th>Program</th>';
    printContent += '<th>Year</th><th>Major</th><th>Time In</th><th>Time Out</th>';
    printContent += '<th>Date</th><th>Status</th>';
    printContent += '</tr></thead><tbody>';

    filteredRows.forEach(row => {
        printContent += '<tr>';
        for (let i = 0; i < row.cells.length; i++) {
            printContent += `<td>${row.cells[i].textContent.trim()}</td>`;
        }
        printContent += '</tr>';
    });

    printContent += '</tbody></table>';
    printContent += '<button onclick="window.print()" style="margin: 20px 0; padding: 10px 20px; background: #4361ee; color: white; border: none; border-radius: 5px; cursor: pointer;">Print Report</button>';
    printContent += '</body></html>';

    printWindow.document.write(printContent);
    printWindow.document.close();

    // Close modal
    closeModal('printModal');
}

// Export Options Handler
function applyExportOptions() {
    // Collect filter values
    const filters = {
        event: document.getElementById('exportEvent')?.value || '',
        college: document.getElementById('exportCollege')?.value || '',
        program: document.getElementById('exportProgram')?.value || '',
        dateFrom: document.getElementById('exportDateFrom')?.value || '',
        dateTo: document.getElementById('exportDateTo')?.value || '',
        timeFrom: document.getElementById('exportTimeFrom')?.value || '',
        timeTo: document.getElementById('exportTimeTo')?.value || '',
        gender: document.getElementById('exportGender')?.value || '',
        format: document.getElementById('exportFormat')?.value || 'csv',
        includeHeaders: document.getElementById('exportIncludeHeaders')?.checked,
        includeSummary: document.getElementById('exportIncludeSummary')?.checked
    };

    // Get filtered table data
    const table = document.getElementById('reportsTable');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr')).filter(row => 
        !row.classList.contains('pagination-hidden') && row.cells.length > 1
    );

    // Filter rows based on criteria
    let filteredRows = rows.filter(row => {
        const cells = row.cells;
        let matches = true;

        // College filter
        if (filters.college && cells[2]?.textContent.trim() !== filters.college) {
            matches = false;
        }

        // Program filter
        if (filters.program && cells[3]?.textContent.trim() !== filters.program) {
            matches = false;
        }

        return matches;
    });

    // Build CSV content
    let csvContent = '';
    
    // Add event info as first line if provided
    if (filters.event) {
        csvContent += `Event/Occasion: ${filters.event}\n`;
    }
    
    // Add generation date
    csvContent += `Generated: ${new Date().toLocaleString()}\n`;
    
    // Add date range if provided
    if (filters.dateFrom || filters.dateTo) {
        csvContent += 'Date Range: ';
        csvContent += filters.dateFrom ? `From ${filters.dateFrom}` : '';
        csvContent += filters.dateTo ? ` To ${filters.dateTo}` : '';
        csvContent += '\n';
    }
    
    csvContent += '\n';

    // Add summary if enabled
    if (filters.includeSummary) {
        const totalRecords = filteredRows.length;
        const completedRecords = filteredRows.filter(row => 
            row.cells[9]?.textContent.includes('COMPLETED')
        ).length;
        const pendingRecords = filteredRows.filter(row => 
            row.cells[9]?.textContent.includes('IN') || row.cells[9]?.textContent.includes('PRESENT')
        ).length;
        
        csvContent += 'SUMMARY STATISTICS\n';
        csvContent += `Total Records,${totalRecords}\n`;
        csvContent += `Completed,${completedRecords}\n`;
        csvContent += `Pending,${pendingRecords}\n`;
        csvContent += '\n';
    }

    // Add column headers if enabled
    if (filters.includeHeaders) {
        csvContent += 'ID,Name,College,Program,Year,Major,Time In,Time Out,Date,Status\n';
    }

    // Add data rows
    filteredRows.forEach(row => {
        const rowData = [];
        for (let i = 0; i < row.cells.length; i++) {
            let cellText = row.cells[i].textContent.trim();
            // Escape quotes and wrap in quotes if contains comma
            if (cellText.includes(',') || cellText.includes('"') || cellText.includes('\n')) {
                cellText = `"${cellText.replace(/"/g, '""')}"`;
            }
            rowData.push(cellText);
        }
        csvContent += rowData.join(',') + '\n';
    });

    // Generate filename
    let filename = 'attendance_report';
    if (filters.event) {
        filename += '_' + filters.event.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    }
    filename += '_' + new Date().toISOString().split('T')[0];
    filename += filters.format === 'xlsx' ? '.xlsx' : '.csv';

    // Create download
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);

    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Show success message (could be improved with a toast notification)
    alert(`Report exported successfully as ${filename}`);

    // Close modal
    closeModal('exportModal');
}
