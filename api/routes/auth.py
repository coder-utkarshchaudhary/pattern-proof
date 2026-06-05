"""
API Endpoints for auth tasks.
Email and password based authentication. JWT based authentication.
Separate endpoints for admin/dev auth. Admin/Dev should not be slowed down by auth workflows and should be able to access all endpoints.

Tasks:
    1. POST /signup
    2. POST /login
    3. GET /me
"""