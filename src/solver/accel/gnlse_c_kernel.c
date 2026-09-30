/*
 * High-Performance C Extension Kernel for GNLSE Pulse Propagation Simulator.
 * Provides OpenMP SIMD fused arithmetic for RK4IP, S-SSFM, and SSFM stepping.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define NPY_NO_DEPRECATED_API NPY_1_7_API_VERSION
#include <numpy/arrayobject.h>
#include <complex.h>
#include <math.h>

#ifdef _OPENMP
#include <omp.h>
#endif

/* 1. Fused Linear Propagation: out_w = in_w * exp_d */
static PyObject* py_fused_linear_step(PyObject* self, PyObject* args) {
    PyArrayObject *in_arr, *exp_arr, *out_arr;
    if (!PyArg_ParseTuple(args, "O!O!O!", &PyArray_Type, &in_arr, &PyArray_Type, &exp_arr, &PyArray_Type, &out_arr)) {
        return NULL;
    }

    npy_intp n = PyArray_SIZE(in_arr);
    const double complex *in_w = (const double complex*)PyArray_DATA(in_arr);
    const double complex *exp_d = (const double complex*)PyArray_DATA(exp_arr);
    double complex *out_w = (double complex*)PyArray_DATA(out_arr);

    #pragma omp parallel for schedule(static) if(n > 512)
    for (npy_intp i = 0; i < n; ++i) {
        out_w[i] = in_w[i] * exp_d[i];
    }

    Py_RETURN_NONE;
}

/* 2. Fused Nonlinear Envelope Generation:
 * Computes intensity = |A(T)|^2 and B(T) = A(T) * ((1 - fr) * I + fr * raman_conv)
 */
static PyObject* py_fused_nonlinear_bt(PyObject* self, PyObject* args) {
    PyArrayObject *at_arr, *conv_arr, *bt_arr, *int_arr;
    double raman_fr;
    if (!PyArg_ParseTuple(args, "O!OdO!O!",
                          &PyArray_Type, &at_arr,
                          &conv_arr,
                          &raman_fr,
                          &PyArray_Type, &bt_arr,
                          &PyArray_Type, &int_arr)) {
        return NULL;
    }

    npy_intp n = PyArray_SIZE(at_arr);
    const double complex *a_t = (const double complex*)PyArray_DATA(at_arr);
    double complex *b_t = (double complex*)PyArray_DATA(bt_arr);
    double *intensity = (double*)PyArray_DATA(int_arr);

    int has_raman = (raman_fr > 0.0 && (PyObject*)conv_arr != Py_None);
    npy_intp stride_conv = 1;
    const double *i_conv = NULL;
    if (has_raman) {
        stride_conv = PyArray_STRIDE((PyArrayObject*)conv_arr, 0) / sizeof(double);
        i_conv = (const double*)PyArray_DATA((PyArrayObject*)conv_arr);
    }

    #pragma omp parallel for schedule(static) if(n > 512)
    for (npy_intp i = 0; i < n; ++i) {
        double re = creal(a_t[i]);
        double im = cimag(a_t[i]);
        double p = re * re + im * im;
        intensity[i] = p;

        double factor;
        if (has_raman) {
            factor = (1.0 - raman_fr) * p + raman_fr * i_conv[i * stride_conv];
        } else {
            factor = p;
        }
        b_t[i] = a_t[i] * factor;
    }

    Py_RETURN_NONE;
}

/* 3. Fused Shock Factor and Gamma Scaling:
 * out_mw[i] = 1j * gamma * shock_factor[i] * b_w[i]
 */
static PyObject* py_fused_apply_shock_gamma(PyObject* self, PyObject* args) {
    PyArrayObject *bw_arr, *shock_arr, *mw_arr;
    double gamma;
    if (!PyArg_ParseTuple(args, "O!OdO!",
                          &PyArray_Type, &bw_arr,
                          &shock_arr,
                          &gamma,
                          &PyArray_Type, &mw_arr)) {
        return NULL;
    }

    npy_intp n = PyArray_SIZE(bw_arr);
    const double complex *b_w = (const double complex*)PyArray_DATA(bw_arr);
    double complex *m_w = (double complex*)PyArray_DATA(mw_arr);
    int has_shock = ((PyObject*)shock_arr != Py_None);
    npy_intp stride_shock = 1;
    const double *shock = NULL;
    if (has_shock) {
        stride_shock = PyArray_STRIDE((PyArrayObject*)shock_arr, 0) / sizeof(double);
        shock = (const double*)PyArray_DATA((PyArrayObject*)shock_arr);
    }

    #pragma omp parallel for schedule(static) if(n > 512)
    for (npy_intp i = 0; i < n; ++i) {
        double scale = has_shock ? (gamma * shock[i * stride_shock]) : gamma;
        double re = creal(b_w[i]);
        double im = cimag(b_w[i]);
        /* 1j * scale * (re + 1j * im) = -scale * im + 1j * scale * re */
        m_w[i] = (-scale * im) + I * (scale * re);
    }

    Py_RETURN_NONE;
}

/* 4. Fused Runge-Kutta Stage Preparation:
 * out_u[i] = a_i[i] + scale * k[i]
 */
static PyObject* py_fused_rk_stage_prep(PyObject* self, PyObject* args) {
    PyArrayObject *ai_arr, *k_arr, *u_arr;
    double scale;
    if (!PyArg_ParseTuple(args, "O!O!dO!",
                          &PyArray_Type, &ai_arr,
                          &PyArray_Type, &k_arr,
                          &scale,
                          &PyArray_Type, &u_arr)) {
        return NULL;
    }

    npy_intp n = PyArray_SIZE(ai_arr);
    const double complex *a_i = (const double complex*)PyArray_DATA(ai_arr);
    const double complex *k = (const double complex*)PyArray_DATA(k_arr);
    double complex *u = (double complex*)PyArray_DATA(u_arr);

    #pragma omp parallel for schedule(static) if(n > 512)
    for (npy_intp i = 0; i < n; ++i) {
        u[i] = a_i[i] + scale * k[i];
    }

    Py_RETURN_NONE;
}

/* 5. Fused Propagation for Stage 4:
 * out_u4_w[i] = exp_half_d[i] * (a_i_w[i] + k3_w[i])
 */
static PyObject* py_fused_rk_prop_stage4(PyObject* self, PyObject* args) {
    PyArrayObject *aiw_arr, *k3w_arr, *exp_arr, *u4w_arr;
    if (!PyArg_ParseTuple(args, "O!O!O!O!",
                          &PyArray_Type, &aiw_arr,
                          &PyArray_Type, &k3w_arr,
                          &PyArray_Type, &exp_arr,
                          &PyArray_Type, &u4w_arr)) {
        return NULL;
    }

    npy_intp n = PyArray_SIZE(aiw_arr);
    const double complex *a_i_w = (const double complex*)PyArray_DATA(aiw_arr);
    const double complex *k3_w = (const double complex*)PyArray_DATA(k3w_arr);
    const double complex *exp_d = (const double complex*)PyArray_DATA(exp_arr);
    double complex *u4_w = (double complex*)PyArray_DATA(u4w_arr);

    #pragma omp parallel for schedule(static) if(n > 512)
    for (npy_intp i = 0; i < n; ++i) {
        u4_w[i] = exp_d[i] * (a_i_w[i] + k3_w[i]);
    }

    Py_RETURN_NONE;
}

/* 6. Fused RK4IP Final Assembly:
 * sum_mid_w = a_i_w + (1/6)*k1_w + (1/3)*k2_w + (1/3)*k3_w
 * out_w = exp_half_d * sum_mid_w + (1/6)*k4_w
 * if filter != None: out_w *= filter[i]
 */
static PyObject* py_fused_rk4ip_assembly(PyObject* self, PyObject* args) {
    PyArrayObject *aiw_arr, *k1w_arr, *k2w_arr, *k3w_arr, *k4w_arr, *exp_arr, *filt_arr, *out_arr;
    if (!PyArg_ParseTuple(args, "O!O!O!O!O!O!OO!",
                          &PyArray_Type, &aiw_arr,
                          &PyArray_Type, &k1w_arr,
                          &PyArray_Type, &k2w_arr,
                          &PyArray_Type, &k3w_arr,
                          &PyArray_Type, &k4w_arr,
                          &PyArray_Type, &exp_arr,
                          &filt_arr,
                          &PyArray_Type, &out_arr)) {
        return NULL;
    }

    npy_intp n = PyArray_SIZE(aiw_arr);
    const double complex *a_i_w = (const double complex*)PyArray_DATA(aiw_arr);
    const double complex *k1_w = (const double complex*)PyArray_DATA(k1w_arr);
    const double complex *k2_w = (const double complex*)PyArray_DATA(k2w_arr);
    const double complex *k3_w = (const double complex*)PyArray_DATA(k3w_arr);
    const double complex *k4_w = (const double complex*)PyArray_DATA(k4w_arr);
    const double complex *exp_d = (const double complex*)PyArray_DATA(exp_arr);
    double complex *out_w = (double complex*)PyArray_DATA(out_arr);

    int has_filter = ((PyObject*)filt_arr != Py_None);
    npy_intp stride_filter = 1;
    const double *filter = NULL;
    if (has_filter) {
        stride_filter = PyArray_STRIDE((PyArrayObject*)filt_arr, 0) / sizeof(double);
        filter = (const double*)PyArray_DATA((PyArrayObject*)filt_arr);
    }

    const double one_sixth = 1.0 / 6.0;
    const double one_third = 1.0 / 3.0;

    #pragma omp parallel for schedule(static) if(n > 512)
    for (npy_intp i = 0; i < n; ++i) {
        double complex mid = a_i_w[i] + one_sixth * k1_w[i] + one_third * k2_w[i] + one_third * k3_w[i];
        double complex val = exp_d[i] * mid + one_sixth * k4_w[i];
        if (has_filter) {
            val *= filter[i * stride_filter];
        }
        out_w[i] = val;
    }

    Py_RETURN_NONE;
}

/* Method registration table */
static PyMethodDef GnlseMethods[] = {
    {"fused_linear_step", py_fused_linear_step, METH_VARARGS, "Vectorized linear propagation step"},
    {"fused_nonlinear_bt", py_fused_nonlinear_bt, METH_VARARGS, "Vectorized intensity and B(T) computation"},
    {"fused_apply_shock_gamma", py_fused_apply_shock_gamma, METH_VARARGS, "Vectorized shock and gamma scaling"},
    {"fused_rk_stage_prep", py_fused_rk_stage_prep, METH_VARARGS, "Vectorized RK stage field addition"},
    {"fused_rk_prop_stage4", py_fused_rk_prop_stage4, METH_VARARGS, "Vectorized RK stage 4 propagation"},
    {"fused_rk4ip_assembly", py_fused_rk4ip_assembly, METH_VARARGS, "Vectorized RK4IP frequency assembly"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef gnlse_c_module = {
    PyModuleDef_HEAD_INIT,
    "gnlse_c_kernel",
    "Compiled OpenMP C acceleration kernel for GNLSE simulator",
    -1,
    GnlseMethods
};

PyMODINIT_FUNC PyInit_gnlse_c_kernel(void) {
    import_array();
    return PyModule_Create(&gnlse_c_module);
}
