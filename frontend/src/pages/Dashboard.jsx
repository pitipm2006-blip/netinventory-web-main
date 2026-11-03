import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import IpamPanel from '../components/IpamPanel';
import MonitoringPanel from '../components/MonitoringPanel';
import { formatApiError } from '../utils/errors';
import TopologyMap from '../TopologyMap';
import AlertsReportsPanel from '../components/AlertsReportsPanel';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const emptyDevice = {
  id_tipo: '',
  id_rack: '',
  nombre_host: '',
  fqdn: '',
  numero_serie: '',
  ip_gestion: '',
  mac_address: '',
  ru_inicio: '',
  estado_operativo: 'activo',
};

async function apiRequest(path, options = {}) {
  const token = localStorage.getItem('netinventory_token');
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(data?.detail));
  }
  return data;
}

function toDevicePayload(form) {
  return {
    id_tipo: Number(form.id_tipo),
    id_rack: form.id_rack ? Number(form.id_rack) : null,
    nombre_host: form.nombre_host.trim(),
    fqdn: form.fqdn.trim() || null,
    numero_serie: form.numero_serie.trim() || null,
    ip_gestion: form.ip_gestion.trim() || null,
    mac_address: form.mac_address.trim() || null,
    ru_inicio: form.ru_inicio ? Number(form.ru_inicio) : null,
    estado_operativo: form.estado_operativo,
  };
}

async function fetchDashboardData() {
  const currentUser = await apiRequest('/api/v1/auth/me');
  const [assetList, typeList, rackList] = await Promise.all([
    apiRequest('/api/v1/devices'),
    apiRequest('/api/v1/device-types'),
    apiRequest('/api/v1/racks'),
  ]);
  let userList = [];
  let roleList = [];
  if (currentUser.rol === 'Admin') {
    [userList, roleList] = await Promise.all([
      apiRequest('/api/v1/users'),
      apiRequest('/api/v1/roles'),
    ]);
  }
  return { currentUser, assetList, typeList, rackList, userList, roleList };
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [devices, setDevices] = useState([]);
  const [deviceTypes, setDeviceTypes] = useState([]);
  const [racks, setRacks] = useState([]);
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [deviceForm, setDeviceForm] = useState(emptyDevice);
  const [editingDevice, setEditingDevice] = useState(null);
  const [userForm, setUserForm] = useState({ nombre_usuario: '', correo: '', password: '', id_rol: '' });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [activeSection, setActiveSection] = useState('overview');

  const applyDashboardData = (data) => {
    setUser(data.currentUser);
    setDevices(data.assetList);
    setDeviceTypes(data.typeList);
    setRacks(data.rackList);
    setUsers(data.userList);
    setRoles(data.roleList);
  };

  const loadData = async () => {
    const data = await fetchDashboardData();
    applyDashboardData(data);
  };

  useEffect(() => {
    let active = true;
    fetchDashboardData()
      .then((data) => {
        if (active) applyDashboardData(data);
      })
      .catch((loadError) => {
        const message = formatApiError(loadError);
        if (message.includes('Token') || message.includes('cuenta')) {
          localStorage.removeItem('netinventory_token');
          navigate('/login', { replace: true });
          return;
        }
        if (active) setError(message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem('netinventory_token');
    navigate('/login', { replace: true });
  };

  const handleDeviceSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setNotice('');
    try {
      const payload = toDevicePayload(deviceForm);
      const path = editingDevice
        ? `/api/v1/devices/${editingDevice.id_dispositivo}`
        : '/api/v1/devices';
      await apiRequest(path, {
        method: editingDevice ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      });
      setDeviceForm(emptyDevice);
      setEditingDevice(null);
      await loadData();
      setNotice(editingDevice ? 'Activo actualizado.' : 'Activo registrado.');
    } catch (requestError) {
      setError(formatApiError(requestError));
    }
  };

  const editDevice = (device) => {
    setEditingDevice(device);
    setDeviceForm({
      id_tipo: String(device.id_tipo),
      id_rack: device.id_rack ? String(device.id_rack) : '',
      nombre_host: device.nombre_host,
      fqdn: device.fqdn || '',
      numero_serie: device.numero_serie || '',
      ip_gestion: device.ip_gestion || '',
      mac_address: device.mac_address || '',
      ru_inicio: device.ru_inicio ? String(device.ru_inicio) : '',
      estado_operativo: device.estado_operativo,
    });
  };

  const deleteDevice = async (device) => {
    if (!window.confirm(`¿Eliminar el activo ${device.nombre_host}?`)) return;
    setError('');
    try {
      await apiRequest(`/api/v1/devices/${device.id_dispositivo}`, { method: 'DELETE' });
      await loadData();
      setNotice('Activo eliminado.');
    } catch (requestError) {
      setError(formatApiError(requestError));
    }
  };

  const createUser = async (event) => {
    event.preventDefault();
    setError('');
    setNotice('');
    try {
      await apiRequest('/api/v1/users', {
        method: 'POST',
        body: JSON.stringify({ ...userForm, id_rol: Number(userForm.id_rol) }),
      });
      setUserForm({ nombre_usuario: '', correo: '', password: '', id_rol: '' });
      await loadData();
      setNotice('Usuario creado.');
    } catch (requestError) {
      setError(formatApiError(requestError));
    }
  };

  const updateUser = async (targetUser, updates) => {
    setError('');
    try {
      await apiRequest(`/api/v1/users/${targetUser.id_usuario}`, {
        method: 'PATCH',
        body: JSON.stringify(updates),
      });
      await loadData();
      setNotice('Usuario actualizado.');
    } catch (requestError) {
      setError(formatApiError(requestError));
    }
  };

  if (loading) {
    return <main className="dashboard-shell"><p>Cargando información...</p></main>;
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <button
          className="sidebar-brand"
          type="button"
          onClick={() => setActiveSection('overview')}
        >
          <span className="brand-mark">NI</span>
          <span>NetInventory<small>Operaciones de red</small></span>
        </button>
        <p className="sidebar-label">ESPACIO DE TRABAJO</p>
        <nav className="sidebar-nav" aria-label="Navegación principal">
          {[
            { id: 'overview', label: 'Resumen', icon: '◫' },
            { id: 'devices', label: 'Activos de red', icon: '▦' },
            { id: 'ipam', label: 'Direcciones IP', icon: '⌘' },
            { id: 'monitoring', label: 'Diagnóstico y monitoreo', icon: '⌁' },
            { id: 'topology', label: 'Topología de red', icon: '🗺️' },
            { id: 'alerts', label: 'Alertas y reportes', icon: '🔔' },
            ...(user?.rol === 'Admin' ? [{ id: 'users', label: 'Usuarios', icon: '♙' }] : []),
          ].map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sidebar-link ${activeSection === item.id ? 'active' : ''}`}
              onClick={() => { setActiveSection(item.id); setError(''); setNotice(''); }}
              aria-current={activeSection === item.id ? 'page' : undefined}
            >
              <span className="sidebar-icon" aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-account">
          <span className="account-avatar">{user?.nombre_usuario?.slice(0, 1).toUpperCase() || 'U'}</span>
          <span className="account-name">{user?.nombre_usuario}<small>{user?.rol}</small></span>
          <button type="button" className="sidebar-logout" onClick={handleLogout} aria-label="Cerrar sesión">↗</button>
        </div>
      </aside>
      <div className="dashboard-content">
      <header className="topbar">
        <div>
          <p className="eyebrow">NetInventory / Sprint 7</p>
          <h1>{{
            overview: 'Resumen de infraestructura',
            devices: 'Activos de red',
            ipam: 'Gestión de direcciones IP',
            monitoring: 'Diagnóstico y monitoreo',
            topology: 'Topología lógica de red',
            alerts: 'Alertas y reportes',
            users: 'Administración de usuarios',
          }[activeSection]}</h1>
        </div>
        <span className="live-indicator"><span />Sistema operativo</span>
      </header>

      {error ? <div className="error-box page-message">{error}</div> : null}
      {notice ? <div className="success-box page-message">{notice}</div> : null}

      {activeSection === 'overview' ? <section className="stats-grid">
        <article className="stat-card blue">
          <span>Activos registrados</span>
          <strong>{devices.length}</strong>
        </article>
        <article className="stat-card green">
          <span>Tipos disponibles</span>
          <strong>{deviceTypes.length}</strong>
        </article>
        {user?.rol === 'Admin' ? (
          <article className="stat-card purple">
            <span>Usuarios</span>
            <strong>{users.length}</strong>
          </article>
        ) : null}
        <article className="stat-card amber">
          <span>Activos con IP de gestión</span>
          <strong>{devices.filter((device) => device.ip_gestion).length}</strong>
        </article>
        <article className="stat-card cyan">
          <span>Activos operativos</span>
          <strong>{devices.filter((device) => device.estado_operativo === 'activo').length}</strong>
        </article>
      </section> : null}

      {activeSection === 'devices' && user?.rol !== 'Auditor' ? (
        <section className="panel">
          <h2>{editingDevice ? 'Editar activo' : 'Registrar activo de red'}</h2>
          <form className="data-form" onSubmit={handleDeviceSubmit}>
            <label>
              Tipo de dispositivo
              <select
                required
                value={deviceForm.id_tipo}
                onChange={(event) => setDeviceForm({ ...deviceForm, id_tipo: event.target.value })}
              >
                <option value="">Selecciona un tipo</option>
                {deviceTypes.map((type) => (
                  <option key={type.id_tipo} value={type.id_tipo}>
                    {type.categoria} — {type.fabricante} {type.modelo}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Nombre de host
              <input required maxLength="120" value={deviceForm.nombre_host} onChange={(event) => setDeviceForm({ ...deviceForm, nombre_host: event.target.value })} />
            </label>
            <label>
              FQDN
              <input maxLength="253" value={deviceForm.fqdn} onChange={(event) => setDeviceForm({ ...deviceForm, fqdn: event.target.value })} placeholder="equipo.ejemplo.local" />
            </label>
            <label>
              Número de serie
              <input maxLength="120" value={deviceForm.numero_serie} onChange={(event) => setDeviceForm({ ...deviceForm, numero_serie: event.target.value })} />
            </label>
            <label>
              IP de gestión
              <input value={deviceForm.ip_gestion} onChange={(event) => setDeviceForm({ ...deviceForm, ip_gestion: event.target.value })} placeholder="192.168.1.10" />
            </label>
            <label>
              Dirección MAC
              <input value={deviceForm.mac_address} onChange={(event) => setDeviceForm({ ...deviceForm, mac_address: event.target.value })} placeholder="AA:BB:CC:DD:EE:FF" />
            </label>
            <label>
              Rack (opcional)
              <select value={deviceForm.id_rack} onChange={(event) => setDeviceForm({ ...deviceForm, id_rack: event.target.value })}>
                <option value="">Sin rack asignado</option>
                {racks.map((rack) => <option key={rack.id_rack} value={rack.id_rack}>{rack.identificador}</option>)}
              </select>
            </label>
            <label>
              Unidad RU inicial (opcional)
              <input type="number" min="1" max="100" value={deviceForm.ru_inicio} onChange={(event) => setDeviceForm({ ...deviceForm, ru_inicio: event.target.value })} />
            </label>
            <label>
              Estado operativo
              <select value={deviceForm.estado_operativo} onChange={(event) => setDeviceForm({ ...deviceForm, estado_operativo: event.target.value })}>
                <option value="activo">Activo</option>
                <option value="mantenimiento">En mantenimiento</option>
                <option value="inactivo">Inactivo</option>
              </select>
            </label>
            <div className="form-actions">
              <button type="submit" disabled={!deviceTypes.length}>{editingDevice ? 'Guardar cambios' : 'Registrar activo'}</button>
              {editingDevice ? (
                <button type="button" className="secondary-button" onClick={() => { setEditingDevice(null); setDeviceForm(emptyDevice); }}>
                  Cancelar
                </button>
              ) : null}
            </div>
          </form>
        </section>
      ) : null}

      {activeSection === 'devices' || activeSection === 'overview' ? <section className="panel">
        <h2>Activos registrados</h2>
        {devices.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Host</th><th>Tipo</th><th>IP de gestión</th><th>MAC</th><th>Serie</th><th>Estado</th><th>Rack</th>
                  {user?.rol !== 'Auditor' ? <th>Acciones</th> : null}
                </tr>
              </thead>
              <tbody>
                {devices.map((device) => (
                  <tr key={device.id_dispositivo}>
                    <td>{device.nombre_host}{device.fqdn ? <small>{device.fqdn}</small> : null}</td>
                    <td>{device.categoria} · {device.fabricante} {device.modelo}</td>
                    <td>{device.ip_gestion || '—'}</td>
                    <td>{device.mac_address || '—'}</td>
                    <td>{device.numero_serie || '—'}</td>
                    <td><span className={`status-pill ${device.estado_operativo}`}>{device.estado_operativo}</span></td>
                    <td>{device.id_rack ?? '—'}</td>
                    {user?.rol !== 'Auditor' ? (
                      <td className="row-actions">
                        <button type="button" className="small-button" onClick={() => editDevice(device)}>Editar</button>
                        {user?.rol === 'Admin' ? <button type="button" className="small-button danger-button" onClick={() => deleteDevice(device)}>Eliminar</button> : null}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="muted">Todavía no hay activos registrados.</p>}
      </section> : null}

      {activeSection === 'ipam' ? <IpamPanel apiRequest={apiRequest} user={user} /> : null}
      {activeSection === 'monitoring' ? (
        <MonitoringPanel apiRequest={apiRequest} devices={devices} user={user} />
      ) : null}
      
      {activeSection === 'alerts' ? <AlertsReportsPanel apiRequest={apiRequest} /> : null}

      {activeSection === 'topology' ? (
        <section className="panel">
          <div className="h-[600px] w-full border border-slate-700 rounded-lg overflow-hidden bg-slate-900">
            <TopologyMap />
          </div>
        </section>
      ) : null}

      {activeSection === 'users' && user?.rol === 'Admin' ? (
        <section className="panel">
          <h2>Administrar usuarios</h2>
          <form className="data-form user-form" onSubmit={createUser}>
            <label>Nombre<input required minLength="2" maxLength="100" value={userForm.nombre_usuario} onChange={(event) => setUserForm({ ...userForm, nombre_usuario: event.target.value })} /></label>
            <label>Correo<input type="email" required value={userForm.correo} onChange={(event) => setUserForm({ ...userForm, correo: event.target.value })} /></label>
            <label>Contraseña (mínimo 8 caracteres)<input type="password" required minLength="8" maxLength="72" value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} /></label>
            <label>Rol<select required value={userForm.id_rol} onChange={(event) => setUserForm({ ...userForm, id_rol: event.target.value })}>
              <option value="">Selecciona un rol</option>
              {roles.map((role) => <option key={role.id_rol} value={role.id_rol}>{role.nombre}</option>)}
            </select></label>
            <div className="form-actions"><button type="submit">Crear usuario</button></div>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>Nombre</th><th>Correo</th><th>Rol</th><th>Estado</th><th>Último acceso</th></tr></thead>
              <tbody>
                {users.map((targetUser) => (
                  <tr key={targetUser.id_usuario}>
                    <td>{targetUser.nombre_usuario}</td>
                    <td>{targetUser.correo}</td>
                    <td>
                      <select value={targetUser.id_rol} onChange={(event) => updateUser(targetUser, { id_rol: Number(event.target.value) })}>
                        {roles.map((role) => <option key={role.id_rol} value={role.id_rol}>{role.nombre}</option>)}
                      </select>
                    </td>
                    <td>
                      <button type="button" className="small-button" onClick={() => updateUser(targetUser, { activo: !targetUser.activo })}>
                        {targetUser.activo ? 'Activo · desactivar' : 'Inactivo · activar'}
                      </button>
                    </td>
                    <td>{targetUser.ultimo_acceso ? new Date(targetUser.ultimo_acceso).toLocaleString() : 'Nunca'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      </div>
    </main>
  );
}