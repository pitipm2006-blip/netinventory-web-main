import { useEffect, useState } from 'react';
import { formatApiError } from '../utils/errors';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const REPORTS = [
  { id: 'devices', label: 'Inventario de activos' },
  { id: 'ipam', label: 'Estado de IPAM' },
  { id: 'alerts', label: 'Historial de alertas' },
];

export default function AlertsReportsPanel({ apiRequest }) {
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const load = () => apiRequest('/api/v1/alerts?limit=50')
      .then((data) => { if (active) { setAlerts(data); setError(''); } })
      .catch((e) => { if (active) setError(formatApiError(e)); });
    load();
    const timer = window.setInterval(load, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [apiRequest]);

  const download = async (report, formato) => {
    setError('');
    try {
      const token = localStorage.getItem('netinventory_token');
      const response = await fetch(`${API_URL}/api/v1/reports/${report}?formato=${formato}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error(`No se pudo generar el reporte (HTTP ${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = `${report}.${formato}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(formatApiError(e));
    }
  };

  return (
    <>
      {error ? <div className="error-box">{error}</div> : null}
      <section className="panel">
        <h2>Exportar reportes</h2>
        <div className="table-wrap"><table>
          <tbody>
            {REPORTS.map((report) => (
              <tr key={report.id}>
                <td>{report.label}</td>
                <td className="row-actions">
                  <button type="button" className="small-button" onClick={() => download(report.id, 'csv')}>CSV</button>
                  <button type="button" className="small-button" onClick={() => download(report.id, 'pdf')}>PDF</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </section>
      <section className="panel">
        <h2>Alertas recientes</h2>
        {alerts.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Activo</th><th>Tipo</th><th>Mensaje</th><th>Estado</th><th>Apertura</th></tr></thead>
            <tbody>
              {alerts.map((alert) => (
                <tr key={alert.id_alerta}>
                  <td>{alert.nombre_host}</td>
                  <td>{alert.tipo}</td>
                  <td>{alert.mensaje}</td>
                  <td><span className={`status-pill ${alert.estado === 'abierta' ? 'inactivo' : 'activo'}`}>{alert.estado}</span></td>
                  <td>{new Date(alert.fecha_apertura).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : <p className="muted">Sin alertas registradas.</p>}
      </section>
    </>
  );
}
