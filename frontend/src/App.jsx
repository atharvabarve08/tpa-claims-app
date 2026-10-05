import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate } from "react-router-dom";
import { getToken, getUser, logout } from "./api";
import Login from "./pages/Login";
import ClaimsList from "./pages/ClaimsList";
import ClaimDetail from "./pages/ClaimDetail";
import Dashboard from "./pages/Dashboard";
import IngestClaim from "./pages/IngestClaim";

function ProtectedRoute({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

function ManagerRoute({ children }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  const user = getUser();
  return user?.role === "TPA_MANAGER" ? children : <Navigate to="/" replace />;
}

function NavBar({ user, onLogout }) {
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    onLogout();
    navigate("/login");
  }

  return (
    <nav className="navbar">
      <div className="navbar-left">
        <Link to="/" className="brand">TPA Claims</Link>
        <Link to="/">Claims List</Link>
        {(user?.role === "CLAIMS_SUBMITTER" || user?.role === "TPA_MANAGER") && (
          <Link to="/ingest">Ingest Claim</Link>
        )}
        {user?.role === "TPA_MANAGER" && <Link to="/dashboard">Analytics</Link>}
      </div>
      <div className="navbar-right">
        {user && (
          <>
            <span className="user-badge">{user.username} · {user.role || "no role"}</span>
            <button onClick={handleLogout}>Log out</button>
          </>
        )}
      </div>
    </nav>
  );
}

export default function App() {
  const [user, setUser] = useState(getUser());

  return (
    <BrowserRouter>
      <NavBar user={user} onLogout={() => setUser(null)} />
      <Routes>
        <Route path="/login" element={<Login onLoggedIn={setUser} />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <ClaimsList />
            </ProtectedRoute>
          }
        />
        <Route
          path="/claims/:id"
          element={
            <ProtectedRoute>
              <ClaimDetail />
            </ProtectedRoute>
          }
        />
        <Route
          path="/ingest"
          element={
            <ProtectedRoute>
              <IngestClaim />
            </ProtectedRoute>
          }
        />
        <Route
          path="/dashboard"
          element={
            <ManagerRoute>
              <Dashboard />
            </ManagerRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}