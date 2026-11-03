import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatApiError } from '../utils/errors';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function Login() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ correo: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(formatApiError(data.detail, 'No se pudo iniciar sesión'));
      }

      localStorage.setItem('netinventory_token', data.access_token);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(formatApiError(err, 'Error desconocido'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="brand-block">
          <span className="brand-chip">NetInventory</span>
          <h1>Acceso al panel</h1>
          <p>Gestión de infraestructura, auditoría y red.</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <label>
            <span>Correo</span>
            <input
              type="email"
              name="correo"
              value={form.correo}
              onChange={handleChange}
              placeholder="admin@netinventory.com"
              required
            />
          </label>

          <label>
            <span>Contraseña</span>
            <input
              type="password"
              name="password"
              value={form.password}
              onChange={handleChange}
              placeholder="••••••••"
              required
            />
          </label>

          {error ? <div className="error-box">{error}</div> : null}

          <button type="submit" disabled={loading}>
            {loading ? 'Conectando...' : 'Iniciar sesión'}
          </button>
        </form>
      </div>
    </div>
  );
}