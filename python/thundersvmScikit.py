from sklearn.base import BaseEstimator
from sklearn.base import RegressorMixin, ClassifierMixin

ThundersvmBase = BaseEstimator
ThundersvmRegressorBase = RegressorMixin
ThundersvmClassifierBase = ClassifierMixin

import numpy as np
import scipy.sparse as sp

from sklearn.utils import check_X_y, column_or_1d, check_array
from sklearn.utils.validation import _num_samples

from ctypes import *
from os import path, curdir
from sys import platform


dirname = path.dirname(path.abspath(__file__))

if platform == "linux" or platform == "linux2":
    shared_library_name = "libthundersvm.so"
elif platform == "win32":
    shared_library_name = "thundersvm.dll"
elif platform == "darwin":
    shared_library_name = "libthundersvm.dylib"
else :
    print ("OS not supported!")
    exit()

if path.exists(path.abspath(path.join(dirname, shared_library_name))):
    lib_path = path.abspath(path.join(dirname, shared_library_name))
else:
    if platform == "linux" or platform == "linux2":
        lib_path = path.join(dirname, '../build/lib/', shared_library_name)
    elif platform == "win32":
        lib_path = path.join(dirname, '../build/bin/Debug/', shared_library_name)
    elif platform == "darwin":
        lib_path = path.join(dirname, '../build/lib/', shared_library_name)

if path.exists(lib_path):
    thundersvm = CDLL(lib_path)
else :
    print ("Please build the library first!")
    exit()

SVM_TYPE = ['c_svc', 'nu_svc', 'one_class', 'epsilon_svr', 'nu_svr']
KERNEL_TYPE = ['linear', 'polynomial', 'rbf', 'sigmoid', 'precomputed']

class SvmModel(ThundersvmBase):
    def __init__(self, kernel, degree,
                 gamma, coef0, C, nu, epsilon,
                 tol, probability, class_weight,
                 shrinking, cache_size, verbose,
                 max_iter, n_jobs, max_mem_size, random_state):
        self.kernel = kernel
        self.degree = degree
        self.gamma = gamma
        self.coef0 = coef0
        self.C = C
        self.nu = nu
        self.epsilon = epsilon
        self.tol = tol
        self.probability = probability
        self.class_weight = class_weight
        self.shrinking = shrinking
        self.cache_size = cache_size
        self.verbose = verbose
        self.max_iter = max_iter
        self.n_jobs = n_jobs
        self.random_state = random_state
        self.max_mem_size = max_mem_size
        thundersvm.model_new.restype = c_void_p
        self.model = thundersvm.model_new(SVM_TYPE.index(self._impl))

    def label_validate(self, y):

        return column_or_1d(y, warn=True).astype(np.float64)

    def fit(self, X, y):
        if self.model is not None:
            thundersvm.model_free(c_void_p(self.model))
        sparse = sp.isspmatrix(X)
        self._sparse = sparse and not callable(self.kernel)
        X, y = check_X_y(X, y, dtype=np.float64, order='C', accept_sparse='csr')
        y = self.label_validate(y)

        solver_type = SVM_TYPE.index(self._impl)


        if self.gamma == 'auto':
            self._gamma = 1.0 / X.shape[1]
        else:
            self._gamma = self.gamma
        if self.kernel not in KERNEL_TYPE:
            print ("The kernel parameter not recognized, please refer to the document.")
            exit()
        else:
            kernel = KERNEL_TYPE.index(self.kernel)

        fit = self._sparse_fit if self._sparse else self._dense_fit
        self.model = thundersvm.model_new(solver_type)
        fit(X, y, solver_type, kernel)
        if self._train_succeed[0] == -1:
            print ("Training failed!")
            return
        self.n_sv = thundersvm.n_sv(c_void_p(self.model))
        csr_row = (c_int * (self.n_sv + 1))()
        csr_col = (c_int * (self.n_sv * self.n_features))()
        csr_data = (c_float * (self.n_sv * self.n_features))()
        data_size = (c_int * 1)()
        thundersvm.get_sv(csr_row, csr_col, csr_data, data_size, c_void_p(self.model))
        dual_coef = (c_float * ((self.n_classes - 1) * self.n_sv))()
        thundersvm.get_coef(dual_coef, self.n_classes, self.n_sv, c_void_p(self.model))
        
        self.dual_coef_ = np.array([dual_coef[index] for index in range(0, (self.n_classes - 1) * self.n_sv)]).astype(float)
        self.dual_coef_ = np.reshape(self.dual_coef_, (self.n_classes - 1, self.n_sv))

        rho_size = int(self.n_classes * (self.n_classes - 1) / 2)
        self.n_binary_model = rho_size
        rho = (c_float * rho_size)()
        thundersvm.get_rho(rho, rho_size, c_void_p(self.model))
        self.intercept_ = np.array([rho[index] for index in range(0, rho_size)]).astype(float)
        
        self.row  = np.array([csr_row[index] for index in range(0, self.n_sv + 1)])
        self.col  = np.array([csr_col[index] for index in range(0, data_size[0])])
        self.data = np.array([csr_data[index] for index in range(0, data_size[0])])
        
        self.support_vectors_ = sp.csr_matrix((self.data, self.col, self.row))
        if self._sparse == False:
            self.support_vectors_ = self.support_vectors_.toarray(order = 'C')
        n_support_ = (c_int * self.n_classes)()
        thundersvm.get_support_classes(n_support_, self.n_classes, c_void_p(self.model))
        
        self.n_support_ = np.array([n_support_[index] for index in range(0, self.n_classes)]).astype(int)

        self.shape_fit_ = X.shape

        return self

    def _dense_fit(self, X, y, solver_type, kernel):

        X = np.asarray(X, dtype=np.float64, order='C')
        samples = X.shape[0]
        features = X.shape[1]
        X_1d = X.ravel()
        data = (c_float * X_1d.size)()
        data[:] = X_1d
        kernel_type = kernel
        label = (c_float * y.size)()
        label[:] = y

        if self.class_weight is None:
            weight_size = 0
            self.class_weight = dict()
        else:
            weight_size = len(self.class_weight)
        weight_label = (c_int * weight_size)()
        weight_label[:] = list(self.class_weight.keys())
        weight = (c_float * weight_size)()
        weight[:] = list(self.class_weight.values())

        n_features = (c_int * 1)()
        n_classes = (c_int * 1)()
        self._train_succeed = (c_int * 1)()
        thundersvm.dense_model_scikit(
            samples, features, data, label, solver_type,
            kernel_type, self.degree, c_float(self._gamma), c_float(self.coef0),
            c_float(self.C), c_float(self.nu), c_float(self.epsilon), c_float(self.tol),
            self.probability, weight_size, weight_label, weight,
            self.verbose, self.max_iter, self.n_jobs, self.max_mem_size,
            n_features, n_classes, self._train_succeed, c_void_p(self.model))
        self.n_features = n_features[0]
        self.n_classes = n_classes[0]




    def _sparse_fit(self, X, y, solver_type, kernel):
        X.data = np.asarray(X.data, dtype=np.float64, order='C')
        X.sort_indices()

        kernel_type = kernel


        data = (c_float * X.data.size)()
        data[:] = X.data
        indices = (c_int * X.indices.size)()
        indices[:] = X.indices
        indptr = (c_int * X.indptr.size)()
        indptr[:] = X.indptr
        label = (c_float * y.size)()
        label[:] = y

        if self.class_weight is None:
            weight_size = 0
            self.class_weight = dict()
        else:
            weight_size = len(self.class_weight)
        weight_label = (c_int * weight_size)()
        weight_label[:] = list(self.class_weight.keys())
        weight = (c_float * weight_size)()
        weight[:] = list(self.class_weight.values())

        n_features = (c_int * 1)()
        n_classes = (c_int * 1)()
        self._train_succeed = (c_int * 1)()
        thundersvm.sparse_model_scikit(
                X.shape[0], data, indptr, indices, label, solver_type,
                kernel_type, self.degree, c_float(self._gamma), c_float(self.coef0),
                c_float(self.C), c_float(self.nu), c_float(self.epsilon), c_float(self.tol),
                self.probability, weight_size, weight_label, weight,
                self.verbose, self.max_iter, self.n_jobs, self.max_mem_size,
                n_features, n_classes, self._train_succeed, c_void_p(self.model))
        self.n_features = n_features[0]
        self.n_classes = n_classes[0]






    def _validate_for_predict(self, X):
        # check_is_fitted(self, 'support_')
        sparse = sp.isspmatrix(X)
        self._sparse = sparse and not callable(self.kernel)
        X = check_array(X, accept_sparse='csr', dtype=np.float64, order="C")
        if self._sparse and not sp.isspmatrix(X):
            X = sp.csr_matrix(X)
        if self._sparse:
            X.sort_indices()

        if sp.issparse(X) and not self._sparse and not callable(self.kernel):
            raise ValueError(
                "cannot use sparse input in %r trained on dense data"
                % type(self).__name__)

        return X

    def predict(self, X):

        X = self._validate_for_predict(X)
        predict = self._sparse_predict if self._sparse else self._dense_predict
        return predict(X)

    def predict_proba(self, X):
        n_classes = (c_int * 1)()
        thundersvm.get_n_classes(c_void_p(self.model), n_classes)
        self.n_classes = n_classes[0]
        if self.probability == 0:
            print ("Should fit with probability = 1")
            return
        else:
            size = X.shape[0] * self.n_classes
            samples = X.shape[0]
            self.predict_pro_ptr = (c_float * size)()
            X = self._validate_for_predict(X)
            if self._sparse:
                self._sparse_predict(X)
            else :
                self._dense_predict(X)
            # size = X.shape[0] * self.n_classes
            # self.predict_pro_ptr = (c_float * size)()
            # X = np.asarray(X, dtype=np.float64, order='C')
            #
            # self.predict_label_ptr = (c_float * X.shape[0])()
            # samples = X.shape[0]
            # features = X.shape[1]
            # X_1d = X.ravel()
            #
            # data = (c_float * X_1d.size)()
            # data[:] = X_1d
            # thundersvm.dense_predict(
            #     samples, features, data,
            #     c_void_p(self.model),
            #     self.predict_label_ptr)
            thundersvm.get_pro(c_void_p(self.model),self.predict_pro_ptr)
            self.predict_prob = np.array([self.predict_pro_ptr[index] for index in range(0, size)])
            self.predict_prob = np.reshape(self.predict_prob, (samples, self.n_classes))
            return self.predict_prob



    def _dense_predict(self, X):

        self.predict_label_ptr = (c_float * X.shape[0])()
        X = np.asarray(X, dtype=np.float64, order='C')
        samples = X.shape[0]
        features = X.shape[1]
        X_1d = X.ravel()

        data = (c_float * X_1d.size)()
        data[:] = X_1d
        thundersvm.dense_predict(
            samples, features, data,
            c_void_p(self.model),
            self.predict_label_ptr)
        
        self.predict_label = np.array([self.predict_label_ptr[index] for index in range(0, X.shape[0])])
        return self.predict_label

    def _sparse_predict(self, X):
        self.predict_label_ptr = (c_float * X.shape[0])()
        data = (c_float * X.data.size)()
        data[:] = X.data
        indices = (c_int * X.indices.size)()
        indices[:] = X.indices
        indptr = (c_int * X.indptr.size)()
        indptr[:] = X.indptr
        thundersvm.sparse_predict(
            X.shape[0], data, indptr, indices,
            c_void_p(self.model),
            self.predict_label_ptr)

        predict_label = [self.predict_label_ptr[index] for index in range(0, X.shape[0])]
        
        self.predict_label = np.asarray(predict_label)
        return self.predict_label

    def decision_function(self, X):
        X = self._validate_for_predict(X)
        n_binary_model = (c_int * 1)()
        thundersvm.get_n_binary_models(c_void_p(self.model), n_binary_model)
        self.n_binary_model = n_binary_model[0]
        if not(self._impl in ['c_svc', 'nu_svc', 'one_class']):
            print ("Not support decision_function!")
            return
        if self._sparse:
            dec_func = self._sparse_decision_function(X)
        else:
            dec_func = self._dense_decision_function(X)
        return dec_func

    def _dense_decision_function(self, X):
        X = check_array(X, dtype=np.float64, order="C")
        samples = X.shape[0]
        features = X.shape[1]
        X_1d = X.ravel()

        data = (c_float * X_1d.size)()
        data[:] = X_1d
        dec_size = X.shape[0] * self.n_binary_model
        dec_value_ptr = (c_float * dec_size)()
        thundersvm.dense_decision(
            samples, features, data, c_void_p(self.model), dec_size, dec_value_ptr
        )
        self.dec_values = np.array([dec_value_ptr[index] for index in range(0, dec_size)]).astype(float)
        self.dec_values = np.reshape(self.dec_values, (X.shape[0], self.n_binary_model))
        return self.dec_values



    def _sparse_decision_function(self, X):
        X.data = np.asarray(X.data, dtype=np.float64, order='C')
        data = (c_float * X.data.size)()
        data[:] = X.data
        indices = (c_int * X.indices.size)()
        indices[:] = X.indices
        indptr = (c_int * X.indptr.size)()
        indptr[:] = X.indptr
        dec_size = X.shape[0] * self.n_binary_model
        dec_value_ptr = (c_float * dec_size)()
        thundersvm.sparse_decision(
            X.shape[0], data, indptr, indices,
            c_void_p(self.model), dec_size, dec_value_ptr)
        self.dec_values = np.array([dec_value_ptr[index] for index in range(0, dec_size)])
        self.dec_values = np.reshape(self.dec_values, (X.shape[0], self.n_binary_model))
        return self.dec_values

    def save_to_file(self, path):
        thundersvm.save_to_file_scikit(c_void_p(self.model), path.encode('utf-8'))

    def load_from_file(self, path):
        thundersvm.load_from_file_scikit(c_void_p(self.model), path.encode('utf-8'))


class SVC(SvmModel, ClassifierMixin):
     _impl = 'c_svc'
     def __init__(self, kernel = 'rbf', degree = 3,
                  gamma = 'auto', coef0 = 0.0, C = 1.0,
                  tol = 0.001, probability = False, class_weight = None,
                  shrinking = False, cache_size = None, verbose = False,
                  max_iter = -1, n_jobs = -1, max_mem_size = -1, random_state = None, decison_function_shape = 'ovo'):
         self.decison_function_shape = decison_function_shape
         super(SVC, self).__init__(
             kernel=kernel, degree=degree, gamma=gamma,
             coef0=coef0, C=C, nu=0., epsilon=0.,
             tol=tol, probability=probability,
             class_weight=class_weight, shrinking = shrinking,
             cache_size = cache_size, verbose = verbose,
             max_iter = max_iter, n_jobs = n_jobs, max_mem_size = max_mem_size, random_state = random_state)



class NuSVC(SvmModel, ClassifierMixin):
    _impl = 'nu_svc'
    def __init__(self, kernel = 'rbf', degree = 3, gamma = 'auto',
                 coef0 = 0.0, nu = 0.5, tol = 0.001,
                 probability = False, shrinking = False, cache_size = None, verbose = False,
                 max_iter = -1, n_jobs = -1, max_mem_size = -1, random_state = None, decison_function_shape = 'ovo'):
        self.decison_function_shape = decison_function_shape
        super(NuSVC, self).__init__(
            kernel = kernel, degree = degree, gamma = gamma,
            coef0 = coef0, C = 0., nu = nu, epsilon= 0.,
            tol = tol, probability = probability, class_weight = None,
            shrinking = shrinking, cache_size = cache_size, verbose = verbose,
            max_iter = max_iter, n_jobs = n_jobs, max_mem_size = max_mem_size, random_state = random_state
        )

class OneClassSVM(SvmModel):
    _impl = 'one_class'
    def __init__(self, kernel = 'rbf', degree = 3, gamma = 'auto',
                 coef0 = 0.0, nu = 0.5, tol = 0.001,
                 shrinking = False, cache_size = None, verbose = False,
                 max_iter = -1, n_jobs = -1, max_mem_size = -1, random_state = None):
        super(OneClassSVM, self).__init__(
            kernel = kernel, degree = degree, gamma = gamma,
            coef0 = coef0, C = 0., nu = nu, epsilon = 0.,
            tol = tol, probability= False, class_weight = None,
            shrinking = shrinking, cache_size = cache_size, verbose = verbose,
            max_iter = max_iter, n_jobs = n_jobs, max_mem_size = max_mem_size, random_state = random_state
        )

    def fit(self, X, y=None):
        super(OneClassSVM, self).fit(X, np.ones(_num_samples(X)))

class SVR(SvmModel, RegressorMixin):
    _impl = 'epsilon_svr'
    def __init__(self, kernel = 'rbf', degree = 3, gamma = 'auto',
                 coef0 = 0.0, C = 1.0, epsilon = 0.1,
                 tol = 0.001, probability = False,
                 shrinking = False, cache_size = None, verbose = False,
                 max_iter = -1, n_jobs = -1,max_mem_size = -1):
        super(SVR, self).__init__(
            kernel = kernel, degree = degree, gamma = gamma,
            coef0 = coef0, C = C, nu = 0., epsilon = epsilon,
            tol = tol, probability = probability, class_weight = None,
            shrinking = shrinking, cache_size = cache_size, verbose = verbose,
            max_iter = max_iter, n_jobs = n_jobs, max_mem_size = max_mem_size, random_state = None
        )

class NuSVR(SvmModel, RegressorMixin):
    _impl = 'nu_svr'
    def __init__(self, kernel = 'rbf', degree = 3, gamma = 'auto',
               coef0 = 0.0, nu = 0.5, C = 1.0, tol = 0.001, probability = False,
               shrinking = False, cache_size = None, verbose = False,
               max_iter = -1, n_jobs = -1, max_mem_size = -1):
        super(NuSVR, self).__init__(
            kernel = kernel, degree = degree, gamma = gamma,
            coef0 = coef0, nu = nu, C = C, epsilon = 0.,
            tol = tol, probability = probability, class_weight = None,
            shrinking = shrinking, cache_size = cache_size, verbose = verbose,
            max_iter = max_iter, n_jobs = n_jobs, max_mem_size = max_mem_size, random_state = None
        )
