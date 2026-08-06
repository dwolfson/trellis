# Egeria Advisor Monitoring Dashboards

Two monitoring dashboard options for real-time system monitoring.

## Terminal Dashboard (Rich-based)

Text-based dashboard using Rich library for terminal display.

### Features
- Real-time collection health monitoring
- Recent query history (prominent display)
- Query performance statistics
- System resource metrics (compact)
- Auto-refresh every 5 seconds

### Usage

```bash
# Run terminal dashboard
python advisor/dashboard/terminal_dashboard.py

# Or use the script
python -m advisor.dashboard.terminal_dashboard
```

### Layout
- **60% space**: Recent queries (last 10-20 queries)
- **40% space**: Collection health
- **Sidebar**: Compact stats and system metrics

### Controls
- `Ctrl+C`: Exit dashboard

---

## Streamlit Dashboard (Web-based)

Interactive web dashboard with charts and detailed visualizations.

### Features
- **Recent Queries Tab**:
  - Configurable query history (10-100 queries)
  - Query latency over time chart
  - Interactive filtering and sorting

- **Collections Tab**:
  - Detailed collection health metrics
  - Entity count, health score, storage size charts
  - Collection usage distribution (pie chart)
  - Per-collection details in tabs

- **Statistics Tab**:
  - Configurable time range (1h, 6h, 12h, 24h)
  - Success rate, cache hit rate
  - Latency percentiles (P50, P95, P99)

- **System Tab**:
  - CPU, Memory, GPU usage with progress bars
  - Disk I/O metrics
  - Network metrics

### Installation

```bash
# Install dashboard dependencies
pip install -e ".[dashboard]"

# Or install manually
pip install streamlit plotly pandas
```

### Usage

```bash
# Run Streamlit dashboard
streamlit run advisor/dashboard/streamlit_dashboard.py

# Or with custom port
streamlit run advisor/dashboard/streamlit_dashboard.py --server.port 8502
```

The dashboard will open in your browser at `http://localhost:8501`

### Configuration

In the sidebar:
- **Auto-refresh**: Enable/disable automatic updates
- **Refresh interval**: 5-60 seconds
- **Quick stats**: 1-hour summary

### Features

#### Auto-refresh
- Automatically updates every N seconds
- Configurable interval
- Manual refresh button available

#### Interactive Charts
- Hover for details
- Zoom and pan
- Download as PNG

#### Responsive Layout
- Wide layout for maximum space
- Tabs for organized content
- Collapsible sidebar

---

## Comparison

| Feature | Terminal Dashboard | Streamlit Dashboard |
|---------|-------------------|---------------------|
| **Interface** | Terminal (TUI) | Web browser |
| **Installation** | Built-in (Rich) | Requires streamlit |
| **Performance** | Lightweight | Heavier (web server) |
| **Interactivity** | Limited | Full interactive |
| **Charts** | Text-based | Plotly charts |
| **Best for** | Quick monitoring | Detailed analysis |
| **Resource usage** | Low | Medium |
| **Remote access** | SSH-friendly | Web-accessible |

---

## Metrics Collected

Both dashboards display:

### Collection Health
- Entity count per collection
- Health score (0-100)
- Storage size (MB)
- Status (healthy/degraded/critical)
- Last update timestamp

### Query Metrics
- Recent query history
- Query text and collection
- Latency (ms)
- Success/failure status
- Cache hit/miss
- Timestamp

### Query Statistics
- Total queries (configurable time range)
- Success rate (%)
- Cache hit rate (%)
- Average latency (ms)
- Latency percentiles (P50, P95, P99)

### System Resources
- CPU usage (%)
- Memory usage (%)
- GPU usage (%) - if available
- Disk I/O (read/write MB)
- Network (sent/recv MB)

---

## Troubleshooting

### Terminal Dashboard

**Issue**: Dashboard not updating
- Check if metrics collector is running
- Verify pgvector connection (`psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c "SELECT 1;"`)
- Check system permissions

**Issue**: Display issues
- Ensure terminal supports Unicode
- Try resizing terminal window
- Check Rich library version

### Streamlit Dashboard

**Issue**: Import errors
```bash
# Install dashboard dependencies
pip install -e ".[dashboard]"
```

**Issue**: Port already in use
```bash
# Use different port
streamlit run advisor/dashboard/streamlit_dashboard.py --server.port 8502
```

**Issue**: Dashboard not updating
- Check auto-refresh is enabled
- Verify metrics collector is running
- Check browser console for errors

**Issue**: Charts not displaying
```bash
# Reinstall plotly
pip install --upgrade plotly
```

---

## Development

### Adding New Metrics

1. Update `advisor/metrics_collector.py` to collect new metrics
2. Add display logic to dashboard(s)
3. Update this README

### Customizing Layout

**Terminal Dashboard**:
- Edit `create_dashboard_layout()` in `terminal_dashboard.py`
- Adjust ratios in `split_row()` and `split_column()`

**Streamlit Dashboard**:
- Edit tab structure in `main()`
- Modify column layouts with `st.columns()`
- Adjust chart configurations

### Testing

```bash
# Test terminal dashboard
python advisor/dashboard/terminal_dashboard.py

# Test Streamlit dashboard
streamlit run advisor/dashboard/streamlit_dashboard.py
```

---

## Performance Tips

### Terminal Dashboard
- Runs efficiently in background
- Low CPU/memory usage
- Good for SSH sessions
- Use `screen` or `tmux` for persistent sessions

### Streamlit Dashboard
- More resource-intensive
- Better for detailed analysis
- Use for periodic monitoring
- Close when not needed to save resources

---

## Future Enhancements

- [ ] Alert notifications
- [ ] Historical data export
- [ ] Custom metric thresholds
- [ ] Email/Slack integration
- [ ] Multi-user support
- [ ] Authentication
- [ ] Dark/light theme toggle
- [ ] Mobile-responsive design